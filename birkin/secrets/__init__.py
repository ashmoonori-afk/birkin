"""Resolve a credential from a secrets manager instead of a plaintext env var.

birkin reads an API key from the environment (``config.PROVIDER_API_KEY_ENV`` ->
``config.get_api_key``) or, failing that, from ``config.json`` -- where the key
sits in plaintext on disk, inside the very directory the file tools already
treat as a control plane. Nothing reached a secrets manager, so a user who keeps
credentials in Bitwarden or 1Password had to export them by hand into the shell
that launches birkin, and every unattended surface (cron, gateway, a systemd
unit) needed the secret written down permanently somewhere.

:func:`apply_all` resolves the configured references once at startup and puts
the values into the process environment, so ``get_api_key`` and every provider
keep working unchanged -- one wiring point, no provider edits.

Zero dependencies is not a compromise here. hermes' Bitwarden and 1Password
backends (``agent/secret_sources/bitwarden.py``, ``onepassword.py``) shell out
to the ``bw`` and ``op`` CLIs themselves, so a manager backend *is* a command
with a known argv. Anything else the user can express directly as ``command``.

Two rules the report obeys, because it is printed at startup and can reach a
log: it never carries a secret value, and it never carries a subprocess's
stderr (which may quote the secret back at you).
"""

from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Optional

# A manager lookup should be quick; a hung one must not wedge startup.
DEFAULT_TIMEOUT = 10.0

# name -> argv builder taking the reference. Both shell out exactly the way
# hermes' own backends do.
_managed_names: set[str] = set()
_managed_names_lock = threading.Lock()

_BACKENDS: dict[str, Callable[[str], list[str]]] = {
    "bitwarden": lambda ref: ["bw", "get", "password", ref],
    "op": lambda ref: ["op", "read", "--no-newline", ref],
}


def argv_for(entry: dict[str, Any]) -> Optional[list[str]]:
    """The command that prints this secret, or ``None`` when it is unusable.

    ``None`` rather than an exception: one malformed entry must not stop the
    other credentials from resolving.
    """
    if not isinstance(entry, dict):
        return None
    source = str(entry.get("source", "")).strip().lower()
    if source == "command":
        argv = entry.get("argv")
        if isinstance(argv, (list, tuple)) and all(
                isinstance(a, str) for a in argv) and argv:
            return list(argv)
        return None
    builder = _BACKENDS.get(source)
    if builder is None:
        return None
    ref = entry.get("ref")
    if not isinstance(ref, str) or not ref.strip():
        return None
    return builder(ref.strip())


def _fetch(argv: list[str], timeout: float) -> tuple[Optional[str], str]:
    """``(value, reason)`` -- exactly one is meaningful.

    The reason is a fixed phrase, never the child's output: a failing ``bw get``
    can echo the vault entry into stderr.
    """
    try:
        done = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, encoding="utf-8",
                              errors="replace")
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout:g}s"
    except FileNotFoundError:
        return None, f"{argv[0]!r} is not installed"
    except OSError as exc:
        return None, f"could not run {argv[0]!r} ({exc.errno})"
    if done.returncode != 0:
        return None, f"command exited {done.returncode}"
    # `bw get` ends its output with a newline, and a key carrying \n 401s.
    value = (done.stdout or "").strip()
    if not value:
        return None, "command produced no output"
    return value, ""


def local_cli_environment(
    required_names: Iterable[str] = (),
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Copy an environment while denying manager-owned secrets by default.

    ``required_names`` is the explicit, exact-name opt-in for one child.  The
    process environment is never edited, avoiding delete/restore races with
    concurrent provider calls.
    """
    source = os.environ if environ is None else environ
    required = frozenset(str(name) for name in required_names)
    with _managed_names_lock:
        denied = _managed_names - required
    return {name: value for name, value in source.items() if name not in denied}


def apply_all(cfg: dict[str, Any],
              env: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Resolve ``cfg["secrets"]`` into ``env`` (the process environment).

    Returns ``{"applied": [...], "failed": {name: reason}, "skipped": [...]}``.
    A variable that is already set wins: an operator's explicit export must
    beat a stored reference, which is also what makes this safe to call more
    than once.
    """
    target = os.environ if env is None else env
    report: dict[str, Any] = {"applied": [], "failed": {}, "skipped": []}
    entries = (cfg or {}).get("secrets") or {}
    if not isinstance(entries, dict):
        return report
    with _managed_names_lock:
        _managed_names.update(str(name) for name in entries)
    for name, entry in entries.items():
        name = str(name)
        if target.get(name):
            report["skipped"].append(name)
            continue
        argv = argv_for(entry)
        if argv is None:
            report["failed"][name] = "no usable source"
            continue
        try:
            timeout = float(entry.get("timeout", DEFAULT_TIMEOUT))
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT
        value, reason = _fetch(argv, timeout)
        if value is None:
            report["failed"][name] = reason
            continue
        target[name] = value
        report["applied"].append(name)
    return report
