# /// script
# requires-python = ">=3.10"
# ///
# ─── How to run ────────────────────────────────────────────────────────────
# uv run python scripts/qa/macos_shell_smoke.py
# ───────────────────────────────────────────────────────────────────────────
"""Exercise macOS shell callers through their real subprocess surfaces."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

from birkin import approvals, github_action, hooks, mcp, monitor, scheduler, store
from birkin.sandbox import PolicyRequest, SandboxJob, SandboxPolicy
from birkin.sandbox_worktree import WorktreeRunner
from birkin.tools import ToolContext, build_registry
from birkin.tools._types import content_text


def command(parts: list[str]) -> str:
    return shlex.join(parts)


def git(repo: Path, *args: str) -> None:
    _ = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def write_script(path: Path, source: str) -> None:
    _ = path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def main() -> int:
    if sys.platform != "darwin":
        print("macOS required", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(
        prefix="birkin-macos-shell-qa-"
    ) as temporary:
        root = Path(temporary)
        home = root / "birkin-home"
        workspace = root / "한글 workspace"
        bin_dir = root / "bin"
        home.mkdir()
        workspace.mkdir()
        bin_dir.mkdir()
        os.environ["BIRKIN_HOME"] = str(home)

        registry = build_registry(
            ToolContext(
                cfg={"shell_approval": "off", "redact_secrets": True},
                client=None,
                cwd=workspace,
            ),
            include={"shell"},
        )
        native = registry.execute(
            "run_shell",
            {
                "command": (
                    "printf 'native\\n' | tr '[:lower:]' '[:upper:]' "
                    "&& (false || printf 'fallback\\n')"
                )
            },
        )

        approval = cast(dict[str, object], approvals.propose(
            category="shell",
            title="macOS shell QA",
            description="exact manual shell approval",
            payload={
                "command": "printf approved-surface",
                "cwd": str(workspace),
            },
            cfg={"auto_approve": []},
            origin="qa",
        ))
        approval_id = approval.get("id")
        if not isinstance(approval_id, str):
            raise TypeError("manual shell proposal has no id")
        approved = cast(
            dict[str, object],
            approvals.approve(approval_id, approved_by="system:qa", approved_via="qa:script"),
        )

        retry_target = workspace / "approved retry.txt"
        retry_target.mkdir()
        _ = (retry_target / "data.txt").write_text(
            "delete after approval",
            encoding="utf-8",
        )
        manual_registry = build_registry(
            ToolContext(
                cfg={"shell_approval": "manual", "redact_secrets": True},
                client=None,
                cwd=workspace,
            ),
            include={"shell"},
        )
        queued = manual_registry.execute(
            "run_shell",
            {"command": f"rm -rf {shlex.quote(str(retry_target))}"},
        )
        pending = cast(list[dict[str, object]], store.list_pending())
        pending_id = pending[0].get("id") if pending else None
        retry = (
            cast(dict[str, object], approvals.approve(pending_id, approved_by="system:qa", approved_via="qa:script"))
            if isinstance(pending_id, str)
            else {}
        )

        scheduler.run_job(
            {
                "id": "qa-scheduler",
                "name": "qa-scheduler",
                "type": "shell",
                "value": "printf scheduler-surface",
            }
        )
        scheduled = next(
            record
            for record in cast(
                list[dict[str, object]],
                store.list_runs(),
            )
            if "qa-scheduler" in str(record.get("summary", ""))
        )

        monitored = monitor.run_script("printf monitor-surface").decode()

        hook_script = workspace / "hook.py"
        write_script(
            hook_script,
            "#!/usr/bin/env python3\n"
            + "import json, sys\n"
            + "payload = json.load(sys.stdin)\n"
            + "print(json.dumps({'context': payload['event']}))\n",
        )
        hooked = hooks.run_hook(
            hooks.HookSpec(
                "pre_llm_call",
                command([sys.executable, str(hook_script)]),
            ),
            {"event": "hook-surface"},
        )

        action_code, action_output = github_action.run_test_command(
            "printf action-surface | tr '[:lower:]' '[:upper:]'"
        )

        fake_claude = bin_dir / "claude"
        write_script(
            fake_claude,
            "#!/bin/sh\nprintf 'mcp-discrete:%s\\n' \"$*\"\n",
        )
        original_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{original_path}"
        try:
            mcp_result = mcp.run(["list"], capture=True)
        finally:
            os.environ["PATH"] = original_path

        repo = root / "repo"
        repo.mkdir()
        git(repo, "init")
        git(repo, "config", "user.email", "qa@example.com")
        git(repo, "config", "user.name", "QA")
        _ = (repo / "tracked.txt").write_text("base", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-m", "base")
        setup_script = root / "setup.py"
        write_script(
            setup_script,
            "from pathlib import Path\n"
            + "Path('setup.txt').write_text('ready', encoding='utf-8')\n",
        )
        created: list[Path] = []
        sandbox = WorktreeRunner(
            repo,
            sandbox_root=root / "sandboxes",
            on_created=created.append,
        ).run(
            SandboxJob(
                command=(
                    sys.executable,
                    "-c",
                    "from pathlib import Path; "
                    + "assert Path('setup.txt').read_text() == 'ready'",
                ),
                setup=(command([sys.executable, str(setup_script)]),),
                request=PolicyRequest(write_paths=("setup.txt",)),
            ),
            SandboxPolicy(write_paths=("setup.txt",)),
            source_env={"PATH": os.environ["PATH"]},
        )

        native_text = content_text(native.content)
        scheduler_summary = str(scheduled["summary"])
        evidence = {
            "action": {
                "exit": action_code,
                "output": action_output.strip(),
            },
            "approval": approved,
            "approval_retry": retry,
            "gateway_native": native_text,
            "hook": hooked,
            "mcp": (mcp_result.stdout or "").strip(),
            "monitor": monitored,
            "sandbox_exit": sandbox.returncode,
            "sandbox_removed": bool(created) and not created[0].exists(),
            "scheduler": scheduler_summary,
            "shell_manual_queued": queued.is_error,
        }
        passed = (
            not native.is_error
            and "NATIVE" in native_text
            and approved.get("ok") is True
            and "approved-surface" in str(approved.get("result"))
            and queued.is_error
            and retry.get("ok") is True
            and not retry_target.exists()
            and "exit 0" in scheduler_summary
            and monitored == "monitor-surface"
            and hooked == {"context": "hook-surface"}
            and action_code == 0
            and action_output.strip() == "ACTION-SURFACE"
            and evidence["mcp"] == "mcp-discrete:mcp list"
            and sandbox.returncode == 0
            and evidence["sandbox_removed"] is True
        )
        evidence["passed"] = passed
        print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
