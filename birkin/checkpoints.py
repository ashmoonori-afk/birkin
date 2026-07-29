"""Snapshot the workspace before the agent changes it, so edits are undoable.

``/undo`` rewinds the *conversation*; nothing ever rewound the *files*. Once
``edit_file`` applied a bad patch or ``run_shell`` deleted the wrong directory,
that was permanent — and ``write_file`` is not even atomic.

Snapshots go into a bare git repository outside the project (default
``~/.birkin/checkpoints/store``), one ref per workspace. Nothing is written
inside the user's own tree: no ``.git`` is created, no existing repository is
touched, no commit of theirs is affected. A workspace that IS a git repo is
snapshotted the same way, with its own history left completely alone.

The whole mechanism is invisible to the model — it is not a tool, and the agent
is never told about it. ``/rollback`` is for the human.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Optional

from . import config

# Never snapshot these — noise, build output, or secrets that have no business
# being copied into ~/.birkin.
DEFAULT_EXCLUDES = [
    ".git/", "node_modules/", ".venv/", "venv/", "__pycache__/", ".mypy_cache/",
    ".pytest_cache/", ".tox/", "dist/", "build/", "target/", ".next/",
    "*.pyc", "*.pyo", "*.log", "*.tmp", "*.swp",
    ".env", ".env.*", "*.pem", "*.key",
    "*.zip", "*.tar", "*.tar.gz", "*.7z", "*.iso", "*.dmg",
    "*.mp4", "*.mov", "*.avi", "*.mkv", "*.png", "*.jpg", "*.jpeg", "*.gif",
    "*.pdf", "*.sqlite", "*.db",
]

# A workspace bigger than this is not worth snapshotting per turn.
_MAX_FILES = 50_000
_GIT_TIMEOUT = 30
_DEFAULT_KEEP = 20


class CheckpointError(RuntimeError):
    """A required pre-mutation snapshot could not be recorded."""


def _run(argv: list[str], env: dict[str, str],
         cwd: Optional[str] = None) -> tuple[int, str]:
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        # Without this every git call flashes a console window, and a global
        # gpgsign/pinentry config could pop a GUI prompt and hang the turn.
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(argv, env=env, cwd=cwd, capture_output=True,
                              text=True, errors="replace",
                              timeout=_GIT_TIMEOUT, **kwargs)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _ref_for(workdir: Path) -> str:
    digest = hashlib.sha256(str(workdir.resolve()).encode("utf-8")).hexdigest()
    return f"refs/birkin/{digest[:16]}"


class CheckpointManager:
    """One bare git store shared by every workspace birkin touches."""

    def __init__(self, *, enabled: bool = True, store_dir: Optional[Path] = None,
                 keep: int = _DEFAULT_KEEP):
        self.enabled = bool(enabled)
        self.store = Path(store_dir) if store_dir \
            else config.birkin_home() / "checkpoints" / "store"
        self.keep = max(1, int(keep))
        self._ready = False
        self._this_turn: set[str] = set()

    # -- plumbing ----------------------------------------------------------

    def _env(self, workdir: Path) -> dict[str, str]:
        """Git environment that keeps the store and the workspace separate.

        GIT_DIR/GIT_WORK_TREE let one bare repo commit another directory's
        contents. The CONFIG_GLOBAL/SYSTEM overrides are not optional: without
        them a user's commit.gpgsign or credential helper runs on every
        snapshot and can block the turn waiting for a passphrase.
        """
        digest = _ref_for(workdir).rsplit("/", 1)[-1]
        index = self.store / "indexes" / digest
        index.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.update(
            GIT_DIR=str(self.store),
            GIT_WORK_TREE=str(workdir),
            GIT_INDEX_FILE=str(index),
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_SYSTEM=os.devnull,
            GIT_TERMINAL_PROMPT="0",
            GIT_OPTIONAL_LOCKS="0",
        )
        return env

    def _ensure_store(self) -> bool:
        if self._ready:
            return True
        try:
            if not (self.store / "HEAD").exists():
                self.store.mkdir(parents=True, exist_ok=True)
                code, _ = _run(["git", "init", "--bare", "--quiet",
                                str(self.store)], dict(os.environ))
                if code != 0:
                    return False
                env = dict(os.environ)
                env.update(GIT_DIR=str(self.store),
                           GIT_CONFIG_GLOBAL=os.devnull,
                           GIT_CONFIG_SYSTEM=os.devnull)
                for key, value in (("user.email", "birkin@localhost"),
                                   ("user.name", "birkin checkpoints"),
                                   ("commit.gpgsign", "false"),
                                   ("gc.auto", "0"),
                                   ("core.autocrlf", "false")):
                    _run(["git", "config", key, value], env)
            info = self.store / "info"
            info.mkdir(parents=True, exist_ok=True)
            # Written unconditionally: `git init` creates its own
            # info/exclude, so an "only if missing" check would leave
            # git's defaults in place and copy .env files and
            # node_modules into ~/.birkin.
            (info / "exclude").write_text(
                "# managed by birkin — see checkpoints.DEFAULT_EXCLUDES\n"
                + "\n".join(DEFAULT_EXCLUDES) + "\n", encoding="utf-8")
        except OSError:
            return False
        self._ready = True
        return True

    # -- taking snapshots --------------------------------------------------

    def new_turn(self) -> None:
        """Start a turn: allow one snapshot per workspace again."""
        self._this_turn.clear()

    def ensure_checkpoint(self, workdir: Any, reason: str = "") -> Optional[str]:
        """Snapshot ``workdir`` unless it already happened this turn.

        Returns the commit hash, or None when the workspace was already
        snapshotted or has no changes. Raises when protection was required but
        the snapshot could not be recorded.
        """
        if not self.enabled:
            return None
        try:
            path = Path(workdir).resolve()
        except OSError as exc:
            raise CheckpointError(f"cannot resolve workspace: {exc}") from exc
        key = str(path)
        if key in self._this_turn:
            return None
        if not path.is_dir():
            return None
        # Refuse the obviously-wrong targets outright.
        if path == Path(path.anchor) or path == Path.home():
            return None
        try:
            commit = self._take(path, reason)
        except CheckpointError:
            raise
        except Exception as exc:
            raise CheckpointError(str(exc)) from exc
        self._this_turn.add(key)
        return commit

    def _take(self, workdir: Path, reason: str) -> Optional[str]:
        if not self._ensure_store():
            raise CheckpointError("could not initialize checkpoint store")
        env = self._env(workdir)
        ref = _ref_for(workdir)

        code, out = _run(["git", "rev-parse", "--verify", "--quiet", ref], env)
        parent = out.strip() if code == 0 else ""

        # Seed the index from the ref tip so `add -A` produces a real diff
        # rather than re-adding the whole tree every time.
        if parent:
            code, out = _run(["git", "read-tree", parent], env)
        else:
            code, out = _run(["git", "read-tree", "--empty"], env)
        if code != 0:
            raise CheckpointError(f"git read-tree failed: {out.strip()}")

        if self._too_big(workdir):
            raise CheckpointError(
                f"workspace exceeds {_MAX_FILES} checkpointable files")
        code, out = _run(["git", "add", "-A", "--", str(workdir)], env)
        if code != 0:
            raise CheckpointError(f"git add failed: {out.strip()}")

        if parent:
            code, out = _run(
                ["git", "diff-index", "--cached", "--quiet", parent], env)
            if code == 0:
                return None            # nothing changed: snapshot is free
            if code != 1:
                raise CheckpointError(
                    f"git diff-index failed: {out.strip()}")

        code, out = _run(["git", "write-tree"], env)
        if code != 0:
            raise CheckpointError(f"git write-tree failed: {out.strip()}")
        tree = out.strip()

        argv = ["git", "commit-tree", tree, "-m", reason or "birkin checkpoint"]
        if parent:
            argv[3:3] = ["-p", parent]
        code, out = _run(argv, env)
        if code != 0:
            raise CheckpointError(f"git commit-tree failed: {out.strip()}")
        commit = out.strip()

        update = ["git", "update-ref", ref, commit]
        if parent:
            update.append(parent)      # compare-and-swap
        code, out = _run(update, env)
        if code != 0:
            raise CheckpointError(f"git update-ref failed: {out.strip()}")
        self._prune(workdir)
        self._record_project(workdir)
        return commit

    def _too_big(self, workdir: Path) -> bool:
        count = 0
        for _root, dirs, files in os.walk(workdir):
            dirs[:] = [d for d in dirs
                       if d not in {".git", "node_modules", ".venv", "venv",
                                    "__pycache__", "dist", "build", "target"}]
            count += len(files)
            if count > _MAX_FILES:
                return True
        return False

    def _prune(self, workdir: Path) -> None:
        """Keep the newest ``keep`` snapshots by rewriting the ref chain."""
        env = self._env(workdir)
        ref = _ref_for(workdir)
        code, out = _run(["git", "rev-list", ref], env)
        if code != 0:
            return
        commits = [c for c in out.split() if c]
        if len(commits) <= self.keep:
            return
        # Re-parent the oldest kept commit onto nothing, dropping the tail.
        cutoff = commits[self.keep - 1]
        code, out = _run(["git", "log", "-1", "--format=%T%n%s", cutoff], env)
        if code != 0:
            return
        lines = out.strip().splitlines()
        if len(lines) < 1:
            return
        tree, subject = lines[0], (lines[1] if len(lines) > 1 else "checkpoint")
        code, out = _run(["git", "commit-tree", tree, "-m", subject], env)
        if code != 0:
            return
        rebased = out.strip()
        for commit in reversed(commits[:self.keep - 1]):
            code, out2 = _run(["git", "log", "-1", "--format=%T%n%s", commit], env)
            if code != 0:
                return
            parts = out2.strip().splitlines()
            code, out2 = _run(["git", "commit-tree", parts[0], "-p", rebased,
                               "-m", parts[1] if len(parts) > 1 else "checkpoint"],
                              env)
            if code != 0:
                return
            rebased = out2.strip()
        _run(["git", "update-ref", ref, rebased], env)

    def _record_project(self, workdir: Path) -> None:
        try:
            meta_dir = self.store / "projects"
            meta_dir.mkdir(parents=True, exist_ok=True)
            digest = _ref_for(workdir).rsplit("/", 1)[-1]
            (meta_dir / f"{digest}.json").write_text(
                json.dumps({"workdir": str(workdir)}), encoding="utf-8")
        except OSError:
            pass

    # -- reading and restoring --------------------------------------------

    def list_checkpoints(self, workdir: Any) -> list[dict[str, str]]:
        path = Path(workdir).resolve()
        if not self._ensure_store():
            return []
        env = self._env(path)
        code, out = _run(["git", "log", _ref_for(path),
                          "--format=%H%x1f%h%x1f%aI%x1f%s"], env)
        if code != 0:
            return []
        entries = []
        for line in out.splitlines():
            parts = line.split("\x1f")
            if len(parts) == 4:
                entries.append({"hash": parts[0], "short": parts[1],
                                "date": parts[2], "reason": parts[3]})
        return entries

    def diff(self, workdir: Any, commit: str) -> str:
        path = Path(workdir).resolve()
        if not self._ensure_store() or not _valid_hash(commit):
            return ""
        env = self._env(path)
        _run(["git", "read-tree", commit], env)
        _run(["git", "add", "-A", "--", str(path)], env)
        code, out = _run(["git", "diff", "--cached", commit], env)
        return out if code == 0 else ""

    def restore(self, workdir: Any, commit: str,
                file: Optional[str] = None) -> tuple[bool, str]:
        """Put the workspace back to ``commit``. Returns (ok, message)."""
        path = Path(workdir).resolve()
        if not self.enabled:
            return False, "checkpoints are disabled"
        if not _valid_hash(commit):
            return False, "not a valid checkpoint id"
        if not self._ensure_store():
            return False, "checkpoint store unavailable"
        if file is not None and not _safe_relpath(file):
            return False, "refusing that path"

        # Snapshot first, so an unwanted rollback is itself undoable.
        self._this_turn.discard(str(path))
        try:
            self.ensure_checkpoint(path, "before rollback")
        except CheckpointError as exc:
            return False, f"could not protect current state: {exc}"

        env = self._env(path)
        target = ["--", file] if file else ["--", "."]
        code, out = _run(["git", "checkout", commit] + target, env, cwd=str(path))
        if code != 0:
            return False, out.strip()[:300]
        return True, (f"restored {file}" if file
                      else "restored files from the checkpoint")


def _valid_hash(value: str) -> bool:
    return bool(value) and len(value) >= 4 and len(value) <= 40 \
        and all(c in "0123456789abcdefABCDEF" for c in value)


def _safe_relpath(value: str) -> bool:
    if not value or value.startswith("-"):
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


# -- the hook the tool registry calls --------------------------------------

def project_root_for(path: Path) -> Path:
    """Walk up to the nearest project marker, so a snapshot covers the project
    rather than whichever subdirectory happened to be edited."""
    markers = {".git", "pyproject.toml", "package.json", "Cargo.toml",
               "go.mod", ".birkin"}
    current = path if path.is_dir() else path.parent
    for candidate in [current, *current.parents]:
        try:
            if any((candidate / m).exists() for m in markers):
                return candidate
        except OSError:
            break
    return current


def preflight(ctx: Any, tool_name: str, tool_input: dict[str, Any]) -> None:
    """Snapshot before a mutating tool runs.

    Emits a ``checkpoint`` event whenever a snapshot is actually recorded, so
    the UI can teach ``/undo`` / ``/rollback`` at the moment there is something
    to undo (the event was silent before — a dead capability).
    """
    manager = getattr(ctx, "checkpoints", None)
    if manager is None or not getattr(manager, "enabled", False):
        return
    commit = None
    if tool_name in ("write_file", "edit_file"):
        raw = (tool_input or {}).get("path", "")
        if not raw:
            return
        target = Path(str(raw)).expanduser()
        if not target.is_absolute():
            target = Path(ctx.cwd) / target
        commit = manager.ensure_checkpoint(project_root_for(target),
                                           f"before {tool_name}")
    elif tool_name == "run_shell":
        command = (tool_input or {}).get("command", "")
        # Reuse shellguard's classifier rather than keeping a second list
        # of destructive patterns in sync with it.
        from .shellguard import detect
        if command and detect(str(command))[0] is not None:
            cwd = (tool_input or {}).get("cwd") or ctx.cwd
            commit = manager.ensure_checkpoint(cwd, "before run_shell")
    if commit and getattr(ctx, "emit", None):
        ctx.emit("checkpoint", {"before": tool_name})
