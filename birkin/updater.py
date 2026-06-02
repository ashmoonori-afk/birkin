"""Self-update: fast-forward birkin's git checkout to its upstream.

``birkin update`` / the gateway ``/update`` command fetch the tracked remote
(``origin``) and fast-forward the local checkout to its upstream branch
(typically ``origin/main``). On the gateway, a successful update that changed
code triggers a hard restart so the new code is loaded.

What gets updated: **everything tracked in the repo** — the ``birkin/`` package
code and the bundled/default skills under ``skills/``. What is NEVER touched: the
per-user state in ``~/.birkin/`` (config, the memory vault, user-added skills in
``~/.birkin/skills/``, pending approvals, saved sessions) — it lives outside the
git repo, so a pull cannot reach it. User-created skills (``create_skill``) are
written to ``~/.birkin/skills/``, so they survive every update.

Safety: a **dirty** working tree (uncommitted changes to tracked files) aborts
the update with a clear message — local work is never silently stashed or reset.
Only a **fast-forward** is performed; a diverged local branch is refused (resolve
manually) rather than merged.

Pure standard library: ``subprocess`` + ``git`` (discrete argv, no ``shell=True``).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Optional


def repo_root() -> Optional[Path]:
    """The git checkout birkin runs from, or ``None`` if it is not a git repo.

    ``updater.py`` lives at ``<repo>/birkin/updater.py``, so the repo root is two
    parents up. Returns ``None`` when ``.git`` is absent (e.g. an installed wheel),
    in which case self-update is not available.
    """
    root = Path(__file__).resolve().parents[1]
    return root if (root / ".git").exists() else None


def _git(root: Path, *args: str, timeout: int = 120) -> tuple[int, str, str]:
    """Run ``git <args>`` in ``root``; return ``(returncode, stdout, stderr)``."""
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                          text=True, errors="replace", timeout=timeout)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def _is_dirty(root: Path) -> bool:
    """True if any TRACKED file has uncommitted changes. Untracked files (``??``)
    don't block a fast-forward, so they are ignored (matches ``git pull``)."""
    rc, out, _ = _git(root, "status", "--porcelain")
    if rc != 0:
        return False  # can't tell → don't falsely block; fetch/merge will report
    return any(line and not line.startswith("??") for line in out.splitlines())


def _read_version(root: Path) -> str:
    """Read birkin's ``__version__`` from the checkout. This is the user-facing
    version (bumped +0.0.1 per commit by the pre-commit hook), shown by ``update``
    instead of a git commit hash. Returns ``'?'`` if unreadable."""
    init = Path(root) / "birkin" / "__init__.py"
    try:
        for line in init.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith("__version__"):
                return s.split("=", 1)[1].strip().strip('"').strip("'") or "?"
    except OSError:
        pass
    return "?"


def _head_date(root: Path) -> str:
    """Short commit date (YYYY-MM-DD) of HEAD — the version's date (≈ push date,
    since each commit is pushed right after). Empty if unavailable."""
    rc, out, _ = _git(root, "log", "-1", "--format=%cd", "--date=short")
    return out if rc == 0 else ""


def _version_label(ver: str, date: str) -> str:
    """'v0.1.3 (2026-06-02)' — version + commit date, or just 'v0.1.3'."""
    return f"v{ver} ({date})" if date else f"v{ver}"


def update(root: Optional[Path] = None) -> dict[str, Any]:
    """Fast-forward the checkout to its upstream. Never raises.

    Returns a status dict: ``{ok, updated, message, ...}``.
    - ``ok`` False on any problem (not a checkout / dirty / fetch fail / diverged).
    - ``updated`` True only when commits were actually pulled (code changed).
    """
    root = Path(root) if root is not None else repo_root()
    if root is None or not (Path(root) / ".git").exists():
        return {"ok": False, "updated": False,
                "message": "birkin is not a git checkout — self-update unavailable. "
                           "Reinstall from the repo to update."}
    root = Path(root)
    try:
        if _is_dirty(root):
            return {"ok": False, "updated": False,
                    "message": "Local uncommitted changes present — update aborted. "
                               "Commit or stash them, then run update again."}
        before = _git(root, "rev-parse", "--short", "HEAD")[1]
        ver_before = _read_version(root)
        rc, _, err = _git(root, "fetch", "--quiet")
        if rc != 0:
            return {"ok": False, "updated": False,
                    "message": f"git fetch failed: {err[:300]}"}
        # Compare upstream vs HEAD: left = behind (in @{u} not HEAD), right = ahead.
        rc, counts, err = _git(root, "rev-list", "--left-right", "--count",
                               "@{u}...HEAD")
        if rc != 0:
            return {"ok": False, "updated": False,
                    "message": f"no upstream to update from: {err[:200]}"}
        parts = counts.split()
        behind = int(parts[0]) if len(parts) == 2 and parts[0].isdigit() else 0
        if behind == 0:
            return {"ok": True, "updated": False, "version": ver_before,
                    "message": "Already up to date — "
                               f"{_version_label(ver_before, _head_date(root))}."}
        rc, _, err = _git(root, "merge", "--ff-only", "@{u}")
        if rc != 0:
            return {"ok": False, "updated": False,
                    "message": f"Cannot fast-forward (local branch diverged): "
                               f"{err[:300]}. Resolve manually with git pull."}
        after = _git(root, "rev-parse", "--short", "HEAD")[1]
        ver_after = _read_version(root)
        changed = _git(root, "diff", "--name-only", before, after)[1]
        n = len([ln for ln in changed.splitlines() if ln.strip()])
        return {"ok": True, "updated": True, "version": ver_after,
                "date": _head_date(root), "behind": behind, "changed": n,
                "message": f"Updated v{ver_before} → "
                           f"{_version_label(ver_after, _head_date(root))}; "
                           f"{behind} commit(s), {n} file(s)."}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"ok": False, "updated": False, "message": f"update failed: {exc}"}
