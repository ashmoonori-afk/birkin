# /// script
# requires-python = ">=3.10"
# ///
# ─── How to run ────────────────────────────────────────────────────────────
# uv run python scripts/qa/windows_shell_smoke.py
# ───────────────────────────────────────────────────────────────────────────
"""Exercise Windows shell callers through their real subprocess surfaces."""

from __future__ import annotations

import json
import os
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
    return subprocess.list2cmdline(parts)


def git(repo: Path, *args: str) -> None:
    _ = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def write_script(path: Path, source: str) -> None:
    _ = path.write_text(source, encoding="utf-8")


def main() -> int:
    if os.name != "nt":
        print("Windows required", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(
        prefix="birkin-windows-shell-qa-"
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
                    "echo native-한글 | findstr native "
                    "&& (cmd /d /c exit 7 || echo fallback)"
                )
            },
        )

        counter = workspace / "approval-count.txt"
        approval_command = command(
            [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; "
                    f"p=Path({str(counter)!r}); "
                    "p.write_text("
                    "(p.read_text(encoding='utf-8') if p.exists() else '')"
                    "+'x', encoding='utf-8')"
                ),
            ]
        )
        approval = cast(
            dict[str, object],
            approvals.propose(
                category="shell",
                title="Windows shell QA",
                description="exact manual shell approval",
                payload={
                    "command": approval_command,
                    "cwd": str(workspace),
                },
                cfg={"auto_approve": []},
                origin="qa",
            ),
        )
        approval_id = approval.get("id")
        if not isinstance(approval_id, str):
            raise TypeError("manual shell proposal has no id")
        approved = cast(dict[str, object], approvals.approve(approval_id, approved_by="system:qa", approved_via="qa:script"))
        replay = cast(dict[str, object], approvals.approve(approval_id, approved_by="system:qa", approved_via="qa:script"))

        retry_target = workspace / "approved retry"
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
        delete_command = f"rmdir /s /q {command([str(retry_target)])}"
        queued = manual_registry.execute(
            "run_shell",
            {"command": delete_command},
        )
        pending = cast(list[dict[str, object]], store.list_pending())
        pending_id = pending[0].get("id") if pending else None
        retry = (
            cast(dict[str, object], approvals.approve(pending_id, approved_by="system:qa", approved_via="qa:script"))
            if isinstance(pending_id, str)
            else {}
        )

        policy_marker = root / "policy-probe-attempted"
        policy_shim = bin_dir / "birkin-policy-probe.cmd"
        policy_script = bin_dir / "birkin-policy-probe.ps1"
        write_script(
            policy_shim,
            "@echo off\r\n"
            + f'if exist "{policy_marker}" goto native\r\n'
            + f'type nul > "{policy_marker}"\r\n'
            + f">&2 echo {policy_script} cannot be loaded because running "
            + "scripts is disabled on this system.\r\n"
            + ">&2 echo PSSecurityException\r\n"
            + "exit /b 1\r\n"
            + ":native\r\n"
            + "echo native-shim-fallback-ok:%*\r\n",
        )
        original_path = os.environ.get("PATH", "")
        original_pathext = os.environ.get("PATHEXT")
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{original_path}"
        os.environ["PATHEXT"] = ".CMD"
        try:
            policy_fallback = registry.execute(
                "run_shell",
                {"command": "birkin-policy-probe payload-한글"},
            )
        finally:
            os.environ["PATH"] = original_path
            if original_pathext is None:
                _ = os.environ.pop("PATHEXT", None)
            else:
                os.environ["PATHEXT"] = original_pathext

        scheduler.run_job(
            {
                "id": "qa-scheduler",
                "name": "qa-scheduler",
                "type": "shell",
                "value": "echo scheduler-surface",
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

        monitored = monitor.run_script("echo monitor-surface").decode().strip()

        hook_script = workspace / "hook.py"
        write_script(
            hook_script,
            "import json, sys\n"
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
            "echo action-surface"
        )

        fake_claude = bin_dir / "claude.cmd"
        write_script(
            fake_claude,
            "@echo off\r\necho mcp-discrete:%*\r\n",
        )
        original_path = os.environ.get("PATH", "")
        original_appdata = os.environ.get("APPDATA")
        isolated_appdata = root / "appdata"
        isolated_appdata.mkdir()
        os.environ["APPDATA"] = str(isolated_appdata)
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{original_path}"
        try:
            mcp_result = mcp.run(["list"], capture=True)
        finally:
            os.environ["PATH"] = original_path
            if original_appdata is None:
                _ = os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = original_appdata

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
        policy_fallback_text = content_text(policy_fallback.content)
        scheduler_summary = str(scheduled["summary"])
        evidence = {
            "action": {
                "exit": action_code,
                "output": action_output.strip(),
            },
            "approval": approved,
            "approval_replay": replay,
            "approval_retry": retry,
            "gateway_native": native_text,
            "hook": hooked,
            "mcp": (mcp_result.stdout or "").strip(),
            "monitor": monitored,
            "policy_fallback": policy_fallback_text,
            "sandbox_exit": sandbox.returncode,
            "sandbox_removed": bool(created) and not created[0].exists(),
            "scheduler": scheduler_summary,
            "shell_manual_queued": queued.is_error,
        }
        passed = (
            not native.is_error
            and "native-한글" in native_text
            and "fallback" in native_text
            and not policy_fallback.is_error
            and "native-shim-fallback-ok:payload-한글" in policy_fallback_text
            and approved.get("ok") is True
            and replay.get("ok") is not True
            and counter.read_text(encoding="utf-8") == "x"
            and queued.is_error
            and retry.get("ok") is True
            and not retry_target.exists()
            and "exit 0" in scheduler_summary
            and monitored == "monitor-surface"
            and hooked == {"context": "hook-surface"}
            and action_code == 0
            and action_output.strip() == "action-surface"
            and evidence["mcp"] == "mcp-discrete:mcp list"
            and sandbox.returncode == 0
            and evidence["sandbox_removed"] is True
        )
        evidence["passed"] = passed
        print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
