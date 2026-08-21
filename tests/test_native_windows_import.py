"""Import-graph safety on platforms without Unix PTY primitives."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Generator
from contextlib import contextmanager
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType

import pytest

_UNIX_ONLY_MODULES = ("fcntl", "pty", "termios")
_UNIX_ONLY_SIGNALS = ("SIGHUP",)

_IMPORT_PROBE = '''
import signal
import sys

BLOCKED = {blocked!r}


class _PlatformBlocker:
    """Refuse Unix-only modules the way a Windows interpreter refuses them."""

    def find_spec(self, name, path=None, target=None):
        if name in BLOCKED:
            raise ModuleNotFoundError(f"No module named {{name!r}}", name=name)
        return None


for name in BLOCKED:
    _ = sys.modules.pop(name, None)
for name in {signals!r}:
    if hasattr(signal, name):
        delattr(signal, name)
sys.meta_path.insert(0, _PlatformBlocker())

import birkin
import birkin.workspace
import birkin.web.server
import birkin.native.server
import birkin.native.session
import birkin.native.product_surfaces
import birkin.cli

for name in BLOCKED:
    assert name not in sys.modules, name
print("IMPORT_OK")
'''


class _PlatformBlocker:
    """Refuse Unix-only modules the way a Windows interpreter refuses them."""

    def find_spec(
        self,
        name: str,
        _path: object = None,
        _target: object = None,
    ) -> ModuleSpec | None:
        if name in _UNIX_ONLY_MODULES:
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return None


@contextmanager
def _unix_pty_modules_blocked() -> Generator[None]:
    removed: dict[str, ModuleType] = {}
    blocker = _PlatformBlocker()
    for name in _UNIX_ONLY_MODULES:
        module = sys.modules.pop(name, None)
        if module is not None:
            removed[name] = module
    sys.meta_path.insert(0, blocker)
    try:
        yield
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.update(removed)


def _run_probe(program: str) -> subprocess.CompletedProcess[str]:
    repository = Path(__file__).resolve().parent.parent
    return subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        cwd=repository,
        timeout=180,
        check=False,
    )


def test_package_web_native_and_cli_import_without_unix_pty_modules() -> None:
    """Given a platform with no fcntl/pty/termios, When the shipped entry-point
    modules are imported, Then every import succeeds."""
    program = _IMPORT_PROBE.format(
        blocked=_UNIX_ONLY_MODULES,
        signals=_UNIX_ONLY_SIGNALS,
    )

    result = _run_probe(program)

    assert result.returncode == 0, result.stderr
    assert "IMPORT_OK" in result.stdout


def test_terminal_creation_without_pty_returns_typed_capability_error() -> None:
    """Given a platform with no PTY support, When a terminal is requested,
    Then a typed unsupported-capability refusal is raised, not an import error."""
    from birkin.workspace import owned_terminal
    from birkin.workspace.contracts import TerminalUnsupported

    authority = owned_terminal.TerminalAuthority(
        session_id="session-1",
        workspace_root=Path.cwd(),
        emit=lambda _event, _payload: None,
        config_loader=lambda: {"auto_approve": ["shell"]},
    )

    with _unix_pty_modules_blocked():
        with pytest.raises(TerminalUnsupported) as refusal:
            _ = authority.create({"actor_kind": "native_human", "cwd": "."})

    assert refusal.value.capability == "terminal"


def test_terminal_signal_table_only_advertises_available_signals() -> None:
    """Given the shipped signal allowlist, When it is inspected, Then every
    advertised name resolves to a signal this platform actually defines."""
    import signal

    from birkin.workspace import owned_terminal

    for name, value in owned_terminal.allowed_signals().items():
        assert getattr(signal, f"SIG{name}", None) == value
