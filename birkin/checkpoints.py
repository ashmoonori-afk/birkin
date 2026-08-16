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
import io
import json
import os
import shutil
import subprocess
import tarfile
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, TypedDict

from . import config
from .checkpoints_timeline import TimelineError, TimelineStore, now

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


class CanonicalStateSnapshot(TypedDict):
    """Canonical per-session state saved beside one file checkpoint."""

    session_id: str
    working_memory: dict[str, Any]
    goal: dict[str, Any] | None


class RestoreMode(str, Enum):
    """Explicit surfaces affected by a checkpoint restore."""

    FILES = "files"
    TASK = "task"
    BOTH = "both"


@dataclass(frozen=True, slots=True)
class RestoreOutcome:
    ok: bool
    message: str
    files_restored: bool = False
    task_restored: bool = False

    def __iter__(self):
        # Preserve the historic ``ok, message = restore(...)`` API.
        yield self.ok
        yield self.message

    def __getitem__(self, index: int):
        return (self.ok, self.message)[index]


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

    def __init__(
        self,
        *,
        enabled: bool = True,
        store_dir: Optional[Path] = None,
        keep: int = _DEFAULT_KEEP,
        state_snapshot: Callable[[], CanonicalStateSnapshot] | None = None,
        state_restore: Callable[[CanonicalStateSnapshot], None] | None = None,
    ):
        self.enabled = bool(enabled)
        self.store = Path(store_dir) if store_dir \
            else config.birkin_home() / "checkpoints" / "store"
        self.keep = max(1, int(keep))
        self._ready = False
        self._this_turn: set[str] = set()
        self._timeline = TimelineStore(self.store.parent / "timeline")
        self._active_tools: list[dict[str, Any]] = []
        self._state_snapshot = state_snapshot
        self._state_restore = state_restore

    def _capture_state(self) -> CanonicalStateSnapshot | None:
        if self._state_snapshot is None:
            return None
        state = self._state_snapshot()
        if set(state) != {"session_id", "working_memory", "goal"}:
            raise CheckpointError("canonical state snapshot has invalid fields")
        if not isinstance(state["session_id"], str) or not state["session_id"]:
            raise CheckpointError("canonical state snapshot needs a session id")
        if not isinstance(state["working_memory"], dict):
            raise CheckpointError("working memory snapshot must be an object")
        goal = state["goal"]
        if goal is not None and not isinstance(goal, dict):
            raise CheckpointError("goal snapshot must be an object or null")
        return CanonicalStateSnapshot(
            session_id=state["session_id"],
            working_memory=dict(state["working_memory"]),
            goal=dict(goal) if goal is not None else None,
        )

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

    def _take(
        self,
        workdir: Path,
        reason: str,
        *,
        prune: bool = True,
    ) -> Optional[str]:
        if not self._ensure_store():
            raise CheckpointError("could not initialize checkpoint store")
        state = self._capture_state()
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
                if (
                    state is None
                    or not self._timeline.task_changed(workdir, parent, state)
                ):
                    return None        # neither files nor task state changed
            elif code != 1:
                raise CheckpointError(
                    f"git diff-index failed ({code}): {out.strip()}")

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
        if state is not None:
            self._timeline.snapshot_task(workdir, commit, state)
        retained = self._prune(workdir, commit) if prune else commit
        self._record_project(workdir)
        return retained

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

    def _prune(self, workdir: Path, newest: str) -> str:
        """Keep the newest ``keep`` snapshots by rewriting the ref chain."""
        env = self._env(workdir)
        ref = _ref_for(workdir)
        code, out = _run(["git", "rev-list", ref], env)
        if code != 0:
            return newest
        commits = [c for c in out.split() if c]
        if len(commits) <= self.keep:
            return newest
        # Re-parent the oldest kept commit onto nothing, dropping the tail.
        cutoff = commits[self.keep - 1]
        code, out = _run(["git", "log", "-1", "--format=%T%n%s", cutoff], env)
        if code != 0:
            return newest
        lines = out.strip().splitlines()
        if len(lines) < 1:
            return newest
        tree, subject = lines[0], (lines[1] if len(lines) > 1 else "checkpoint")
        code, out = _run(["git", "commit-tree", tree, "-m", subject], env)
        if code != 0:
            return newest
        rebased = out.strip()
        rewritten = {cutoff: rebased}
        for commit in reversed(commits[:self.keep - 1]):
            code, out2 = _run(["git", "log", "-1", "--format=%T%n%s", commit], env)
            if code != 0:
                return newest
            parts = out2.strip().splitlines()
            code, out2 = _run(["git", "commit-tree", parts[0], "-p", rebased,
                               "-m", parts[1] if len(parts) > 1 else "checkpoint"],
                              env)
            if code != 0:
                return newest
            rebased = out2.strip()
            rewritten[commit] = rebased
        self._timeline.copy_task_snapshots(workdir, rewritten)
        code, _ = _run(["git", "update-ref", ref, rebased], env)
        if code != 0:
            return newest
        self._timeline.remove_task_snapshots(
            workdir,
            set(rewritten) - set(rewritten.values()),
        )
        return rewritten.get(newest, newest)

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
            if len(parts) == 4 and not parts[3].startswith("after "):
                # After snapshots anchor timeline/fork lineage but are not
                # duplicate human restore points in the checkpoint picker.
                entries.append({"hash": parts[0], "short": parts[1],
                                "date": parts[2], "reason": parts[3]})
        return entries

    def diff(self, workdir: Any, commit: str) -> str:
        return str(self.diff_preview(workdir, commit)["patch"])

    def diff_preview(self, workdir: Any, commit: str) -> dict[str, Any]:
        """Return aggregate and per-file patches from ``commit`` to now."""
        path = Path(workdir).resolve()
        empty: dict[str, Any] = {
            "checkpoint": commit, "patch": "", "files": [],
            "additions": 0, "deletions": 0,
        }
        if not self._ensure_store() or not _valid_hash(commit):
            return empty
        env = self._env(path)
        _run(["git", "read-tree", commit], env)
        code, _ = _run(["git", "add", "-A", "--", str(path)], env)
        if code != 0:
            return empty
        code, patch = _run(["git", "diff", "--cached", "--no-ext-diff", commit], env)
        if code != 0:
            return empty
        _, stats = _run(["git", "diff", "--cached", "--numstat", commit], env)
        files: list[dict[str, Any]] = []
        additions = deletions = 0
        for line in stats.splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            added = int(parts[0]) if parts[0].isdigit() else 0
            removed = int(parts[1]) if parts[1].isdigit() else 0
            name = parts[2]
            _, file_patch = _run(
                ["git", "diff", "--cached", "--no-ext-diff", commit, "--", name], env)
            files.append({"path": name, "additions": added,
                          "deletions": removed, "patch": file_patch})
            additions += added
            deletions += removed
        return {"checkpoint": commit, "patch": patch, "files": files,
                "additions": additions, "deletions": deletions}

    def restore(self, workdir: Any, commit: str,
                file: Optional[str] = None, *,
                mode: RestoreMode | str = RestoreMode.FILES) -> RestoreOutcome:
        """Restore files, durable task state, or both from ``commit``.

        File restores mutate only the workspace. Task restores mutate only the
        checkpoint sidecar consumed by session integrations. Both first records
        an undo checkpoint, making the destructive operation reversible.
        """
        path = Path(workdir).resolve()
        try:
            selected = RestoreMode(mode)
        except ValueError:
            return RestoreOutcome(False, "invalid restore mode")
        if not self.enabled:
            return RestoreOutcome(False, "checkpoints are disabled")
        if not _valid_hash(commit):
            return RestoreOutcome(False, "not a valid checkpoint id")
        if not self._ensure_store():
            return RestoreOutcome(False, "checkpoint store unavailable")
        env = self._env(path)
        code, _ = _run(
            ["git", "merge-base", "--is-ancestor", commit, _ref_for(path)],
            env,
        )
        if code != 0:
            return RestoreOutcome(
                False,
                "checkpoint does not belong to this workspace",
            )
        if file is not None and not _safe_relpath(file):
            return RestoreOutcome(False, "refusing that path")
        if file is not None and selected is RestoreMode.TASK:
            return RestoreOutcome(False, "a file cannot be combined with task-only restore")
        if (
            selected in (RestoreMode.TASK, RestoreMode.BOTH)
            and self._state_restore is None
        ):
            return RestoreOutcome(
                False,
                "canonical state restore is unavailable",
            )
        pending_state: CanonicalStateSnapshot | None = None
        if selected in (RestoreMode.TASK, RestoreMode.BOTH):
            try:
                restored = self._timeline.restore_task(path, commit)
                pending_state = CanonicalStateSnapshot(
                    session_id=restored["session_id"],
                    working_memory=restored["working_memory"],
                    goal=restored.get("goal"),
                )
                current = self._capture_state()
                if current is None:
                    return RestoreOutcome(
                        False,
                        "canonical state snapshot is unavailable",
                    )
                if pending_state["session_id"] != current["session_id"]:
                    return RestoreOutcome(
                        False,
                        "checkpoint belongs to a different session",
                    )
            except TimelineError as exc:
                return RestoreOutcome(False, str(exc))
            except (KeyError, TypeError, ValueError) as exc:
                return RestoreOutcome(
                    False,
                    f"invalid canonical state snapshot: {exc}",
                )

        # Protect both current surfaces before changing either one.
        self._this_turn.discard(str(path))
        rollback_head = self._head(path)
        try:
            undo = self._take(path, "before rollback", prune=False)
        except (CheckpointError, TimelineError, OSError) as exc:
            return RestoreOutcome(False, f"could not protect current state: {exc}")

        def finish(outcome: RestoreOutcome) -> RestoreOutcome:
            if undo is not None:
                self._prune(path, undo)
            return outcome

        files_restored = False
        task_restored = False

        def task_failure(message: str) -> RestoreOutcome:
            nonlocal files_restored
            rollback_target = undo or rollback_head
            if files_restored and rollback_target:
                target = ["--", file] if file else ["--", "."]
                code, out = _run(
                    ["git", "checkout", rollback_target] + target,
                    self._env(path),
                    cwd=str(path),
                )
                if code != 0:
                    return finish(RestoreOutcome(
                        False,
                        f"{message}; file rollback failed: {out.strip()[:200]}",
                        True,
                        False,
                    ))
                files_restored = False
            return finish(RestoreOutcome(
                False,
                message,
                files_restored,
                False,
            ))

        if selected in (RestoreMode.FILES, RestoreMode.BOTH):
            env = self._env(path)
            target = ["--", file] if file else ["--", "."]
            code, out = _run(["git", "checkout", commit] + target, env, cwd=str(path))
            if code != 0:
                return finish(RestoreOutcome(False, out.strip()[:300]))
            files_restored = True
        if selected in (RestoreMode.TASK, RestoreMode.BOTH):
            try:
                if self._state_restore is None or pending_state is None:
                    return task_failure(
                        "canonical state restore is unavailable"
                    )
                self._state_restore(pending_state)
            except TimelineError as exc:
                return task_failure(str(exc))
            except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
                return task_failure(
                    f"invalid canonical state snapshot: {exc}"
                )
            task_restored = True
        surfaces = " and ".join(
            name for name, changed in (("files", files_restored), ("task state", task_restored))
            if changed
        )
        return finish(RestoreOutcome(
            True,
            f"restored {surfaces} from the checkpoint",
            files_restored,
            task_restored,
        ))

    def _head(self, workdir: Path) -> str:
        if not self._ensure_store():
            return ""
        code, out = _run(
            ["git", "rev-parse", "--verify", "--quiet", _ref_for(workdir)],
            self._env(workdir),
        )
        return out.strip() if code == 0 else ""

    def begin_tool(self, workdir: Any, tool: str,
                   tool_input: dict[str, Any]) -> None:
        """Open one timeline event and capture its before file/task state."""
        workspace = Path(workdir).resolve()
        mutating = (
            tool in {"write_file", "edit_file", "run_shell"}
            and not bool(tool_input.get("_read_only"))
        )
        before = ""
        if mutating:
            before = self.ensure_checkpoint(workspace, f"before {tool}") or self._head(workspace)
        else:
            before = self._head(workspace)
        touched: list[str] = []
        raw_path = tool_input.get("path")
        if tool in {"write_file", "edit_file"} and raw_path:
            candidate = Path(str(raw_path))
            if candidate.is_absolute():
                try:
                    candidate = candidate.resolve().relative_to(workspace)
                except ValueError:
                    candidate = Path(candidate.name)
            touched = [candidate.as_posix()]
        self._active_tools.append({
            "id": uuid.uuid4().hex,
            "workspace": workspace,
            "tool": tool,
            "before": before,
            "touched_hint": touched,
            "mutating": mutating,
            "started_at": now(),
        })

    def complete_tool(self, tool: str, *, failed: bool) -> None:
        """Close the latest matching tool event and persist its after state."""
        index = next(
            (i for i in range(len(self._active_tools) - 1, -1, -1)
             if self._active_tools[i]["tool"] == tool),
            None,
        )
        if index is None:
            return
        active = self._active_tools.pop(index)
        workspace: Path = active["workspace"]
        before = str(active["before"])
        after = before
        if active["mutating"]:
            after = self._take(workspace, f"after {tool}") or self._head(workspace) or before
        touched = list(active["touched_hint"])
        if before and after and before != after:
            code, out = _run(
                ["git", "diff", "--name-only", before, after], self._env(workspace))
            if code == 0:
                touched = sorted(set(touched) | set(out.splitlines()))
        self._timeline.append(workspace, "timeline", {
            "id": active["id"], "tool": tool,
            "started_at": active["started_at"], "finished_at": now(),
            "status": "failed" if failed else "succeeded",
            "touched": touched, "before": before, "after": after,
        })

    def timeline(self, workdir: Any) -> list[dict[str, Any]]:
        return self._timeline.entries(Path(workdir).resolve(), "timeline")

    def lineage(self, workdir: Any) -> list[dict[str, Any]]:
        return self._timeline.entries(Path(workdir).resolve(), "lineage")

    def _seed(self, workspace: Path, checkpoint: str, target: Path) -> None:
        env = self._env(workspace)
        code, _ = _run(
            ["git", "merge-base", "--is-ancestor", checkpoint, _ref_for(workspace)], env)
        if code != 0:
            raise CheckpointError("checkpoint does not belong to this workspace")
        for child in target.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        proc = subprocess.run(
            ["git", f"--git-dir={self.store}", "archive", checkpoint],
            capture_output=True, check=False,
        )
        if proc.returncode != 0:
            raise CheckpointError("could not export checkpoint tree")
        with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as archive:
            archive.extractall(target, filter="data")

    def fork(self, workdir: Any, checkpoint: str, command: Sequence[str], *,
             runner: Any = None, policy: Any = None,
             on_output: Callable[[str], None] | None = None) -> Any:
        """Run an alternate attempt in an ephemeral worktree seeded at a checkpoint."""
        from .sandbox import SandboxJob, SandboxPolicy
        from .sandbox_worktree import WorktreeRunner

        workspace = Path(workdir).resolve()
        if not command or not _valid_hash(checkpoint):
            raise CheckpointError("fork requires a checkpoint and command")
        selected_runner = runner or WorktreeRunner(workspace)
        selected_policy = policy or SandboxPolicy()
        fork_id = uuid.uuid4().hex
        result = selected_runner.run(
            SandboxJob(command=tuple(command)), selected_policy,
            seed=lambda target: self._seed(workspace, checkpoint, target),
        )
        if on_output is not None:
            on_output(result.stdout)
        self._timeline.append(workspace, "lineage", {
            "id": fork_id, "kind": "alternate", "checkpoint": checkpoint,
            "created_at": now(), "command": list(command),
            "status": "succeeded" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
        })
        return result


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
    """Open a per-tool timeline event, checkpointing mutating tools first."""
    manager = getattr(ctx, "checkpoints", None)
    if manager is None or not getattr(manager, "enabled", False):
        return
    workspace = Path(ctx.cwd).resolve()
    if not hasattr(manager, "begin_tool"):
        # Compatibility for lightweight integration adapters implementing the
        # original manager protocol.
        if tool_name in ("write_file", "edit_file"):
            raw = (tool_input or {}).get("path", "")
            if not raw:
                return
            target = Path(str(raw)).expanduser()
            if not target.is_absolute():
                target = workspace / target
            commit = manager.ensure_checkpoint(project_root_for(target), f"before {tool_name}")
            if commit and getattr(ctx, "emit", None):
                ctx.emit("checkpoint", {"before": tool_name})
        return
    if tool_name in ("write_file", "edit_file"):
        raw = (tool_input or {}).get("path", "")
        if not raw:
            return
        target = Path(str(raw)).expanduser()
        if not target.is_absolute():
            target = workspace / target
        workspace = project_root_for(target)
    elif tool_name == "run_shell":
        command = (tool_input or {}).get("command", "")
        from .shellguard import detect
        # Benign shell calls still appear in the timeline, but do not create
        # snapshots merely by being observed.
        if not command or detect(str(command))[0] is None:
            manager.begin_tool(workspace, tool_name, {**tool_input, "_read_only": True})
            return
        workspace = Path((tool_input or {}).get("cwd") or ctx.cwd).resolve()
    before = manager._head(workspace)
    manager.begin_tool(workspace, tool_name, tool_input or {})
    if manager._head(workspace) != before and getattr(ctx, "emit", None):
        ctx.emit("checkpoint", {"before": tool_name})


def postflight(ctx: Any, tool_name: str, *, failed: bool) -> None:
    manager = getattr(ctx, "checkpoints", None)
    if (manager is not None and getattr(manager, "enabled", False)
            and hasattr(manager, "complete_tool")):
        manager.complete_tool(tool_name, failed=failed)
