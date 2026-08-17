"""Tool checkpoint timeline, typed restore surfaces, and sandbox lineage."""

from __future__ import annotations

import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from birkin import checkpoints
from birkin.checkpoints import RestoreMode
from birkin.sandbox import SandboxPolicy
from birkin.sandbox_worktree import WorktreeRunner
from birkin.tools import ToolContext, build_registry

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))


@pytest.fixture
def work(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (root / "main.py").write_text("before\n", encoding="utf-8")
    return root


def test_timeline_assembles_before_after_for_tool_execution(work: Path) -> None:
    manager = checkpoints.CheckpointManager()
    ctx = ToolContext(cfg={"spill_threshold": 0}, client=None, cwd=work, checkpoints=manager)
    result = build_registry(ctx, include={"files"}).execute(
        "write_file", {"path": "main.py", "content": "after\n"}
    )

    assert not result.is_error
    event = manager.timeline(work)[0]
    assert event["tool"] == "write_file"
    assert event["before"] and event["after"]
    assert event["before"] != event["after"]
    assert event["touched"] == ["main.py"]
    assert event["status"] == "succeeded"
    assert event["started_at"] <= event["finished_at"]


def test_diff_preview_is_structured_per_file_and_aggregate(work: Path) -> None:
    manager = checkpoints.CheckpointManager()
    checkpoint = manager.ensure_checkpoint(work, "before edit")
    assert checkpoint
    (work / "main.py").write_text("after\n", encoding="utf-8")
    (work / "new.txt").write_text("new\n", encoding="utf-8")

    preview = manager.diff_preview(work, checkpoint)

    assert {item["path"] for item in preview["files"]} == {"main.py", "new.txt"}
    assert preview["additions"] == 2
    assert preview["deletions"] == 1
    assert "main.py" in preview["patch"] and "new.txt" in preview["patch"]
    assert all("patch" in item for item in preview["files"])


@pytest.mark.parametrize(
    ("mode", "files_changed", "task_changed"),
    [
        (RestoreMode.FILES, True, False),
        (RestoreMode.TASK, False, True),
        (RestoreMode.BOTH, True, True),
    ],
)
def test_restore_mode_touched_surface_matrix(
    work: Path, mode: RestoreMode, files_changed: bool, task_changed: bool
) -> None:
    state = {
        "session_id": "timeline-session",
        "working_memory": {"messages": ["before"]},
        "goal": None,
    }

    def restore(snapshot):
        state.clear()
        state.update(deepcopy(snapshot))

    manager = checkpoints.CheckpointManager(
        state_snapshot=lambda: deepcopy(state),
        state_restore=restore,
    )
    checkpoint = manager.ensure_checkpoint(work, "before edit")
    assert checkpoint
    (work / "main.py").write_text("after\n", encoding="utf-8")
    state["working_memory"]["messages"] = ["after"]

    outcome = manager.restore(work, checkpoint, mode=mode)

    assert outcome.ok
    assert outcome.files_restored is files_changed
    assert outcome.task_restored is task_changed
    expected_file = "before\n" if files_changed else "after\n"
    expected_task = "before" if task_changed else "after"
    assert (work / "main.py").read_text(encoding="utf-8") == expected_file
    assert state["working_memory"]["messages"] == [expected_task]


def test_both_restore_rolls_files_back_when_task_restore_fails(
    work: Path,
) -> None:
    state = {
        "session_id": "transaction-session",
        "working_memory": {"messages": ["before"]},
        "goal": None,
    }
    manager = checkpoints.CheckpointManager(
        state_snapshot=lambda: deepcopy(state),
        state_restore=lambda _snapshot: (_ for _ in ()).throw(
            ValueError("task write failed")
        ),
    )
    checkpoint = manager.ensure_checkpoint(work, "before edit")
    assert checkpoint
    (work / "main.py").write_text("after\n", encoding="utf-8")

    outcome = manager.restore(
        work,
        checkpoint,
        mode=RestoreMode.BOTH,
    )

    assert outcome.ok is False
    assert outcome.files_restored is False
    assert (work / "main.py").read_text(encoding="utf-8") == "after\n"


def test_both_restore_uses_head_when_no_new_undo_commit_exists(
    work: Path,
) -> None:
    state = {
        "session_id": "no-undo-session",
        "working_memory": {"messages": ["old"]},
        "goal": None,
    }
    manager = checkpoints.CheckpointManager(
        state_snapshot=lambda: deepcopy(state),
        state_restore=lambda _snapshot: (_ for _ in ()).throw(
            ValueError("task write failed")
        ),
    )
    old = manager.ensure_checkpoint(work, "old")
    assert old
    manager.new_turn()
    (work / "main.py").write_text("new\n", encoding="utf-8")
    state["working_memory"]["messages"] = ["new"]
    newest = manager.ensure_checkpoint(work, "new")
    assert newest
    manager.new_turn()

    outcome = manager.restore(
        work,
        old,
        mode=RestoreMode.BOTH,
    )

    assert outcome.ok is False
    assert outcome.files_restored is False
    assert (work / "main.py").read_text(encoding="utf-8") == "new\n"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "main.txt").write_text("checkpoint\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    return repo


def test_fork_seeds_checkpoint_and_records_lineage(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manager = checkpoints.CheckpointManager(store_dir=tmp_path / "store")
    checkpoint = manager.ensure_checkpoint(repo, "failure point")
    assert checkpoint
    (repo / "main.txt").write_text("current state\n", encoding="utf-8")
    seen: list[str] = []
    runner = WorktreeRunner(repo, sandbox_root=tmp_path / "sandboxes")
    command = (
        sys.executable,
        "-c",
        "import pathlib; print(pathlib.Path('main.txt').read_text().strip())",
    )

    result = manager.fork(
        repo, checkpoint, command, runner=runner, policy=SandboxPolicy(), on_output=seen.append
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "checkpoint"
    assert (repo / "main.txt").read_text(encoding="utf-8") == "current state\n"
    lineage = manager.lineage(repo)
    assert lineage[-1]["checkpoint"] == checkpoint
    assert lineage[-1]["status"] == "succeeded"
    assert lineage[-1]["kind"] == "alternate"
