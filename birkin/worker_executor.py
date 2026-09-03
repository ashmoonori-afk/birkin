"""Digest-verified worker execution through discrete subprocess argv."""

from __future__ import annotations

import json
import subprocess
import sys

from typing_extensions import assert_never

from .worker_request import (
    DaedalusCreate,
    DaedalusNote,
    DaedalusProfile,
    DaedalusRefresh,
    DaedalusShow,
    HarnessRequest,
    MoiraiList,
    MoiraiResume,
    MoiraiRun,
    MoiraiStatus,
    MorpheusRun,
    NeurosisRequest,
    OdysseyRequest,
    WorkerRequest,
    approved_request,
)


class WorkerExecutionError(RuntimeError):
    """An approved worker process timed out or returned failure."""


def argv(request: WorkerRequest) -> tuple[str, ...]:
    """Translate one typed request to argv with exhaustive variant handling."""
    prefix = (sys.executable, "-m", "birkin")
    match request:
        case MoiraiRun(script=script, task=task):
            args_json = json.dumps(
                {"task": task},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            return (*prefix, "moirai", "run", script, "--args", args_json, "--defaults")
        case MoiraiList(limit=limit):
            return (*prefix, "moirai", "list", "--limit", str(limit))
        case MoiraiStatus(run_id=run_id):
            return (*prefix, "moirai", "status", run_id)
        case MoiraiResume(run_id=run_id):
            return (*prefix, "moirai", "resume", run_id)
        case MorpheusRun(dry_run=dry_run):
            return (*prefix, "morpheus", *(("--dry-run",) if dry_run else ()))
        case HarnessRequest(action=action, target=target, scope=scope):
            target_argv = (target,) if target else ()
            return (*prefix, "harness", action, *target_argv, "--scope", scope)
        case OdysseyRequest(goal=goal):
            return (*prefix, "odyssey", goal)
        case NeurosisRequest(idea=idea, resolution=resolution):
            return (*prefix, "neurosis", idea, f"--{resolution}")
        case DaedalusCreate(slug=slug, root=root):
            root_argv = ("--root", root) if root else ()
            return (*prefix, "daedalus", "create", slug, *root_argv)
        case DaedalusRefresh(slug=slug, root=root, token=token):
            root_argv = ("--root", root) if root else ()
            return (
                *prefix,
                "daedalus",
                "refresh",
                slug,
                *root_argv,
                "--expected-token",
                token,
            )
        case DaedalusShow(slug=slug):
            return (*prefix, "daedalus", "show", slug)
        case DaedalusNote(slug=slug, text=text, refs=refs):
            ref_argv = tuple(part for ref in refs for part in ("--ref", ref))
            return (*prefix, "daedalus", "note", slug, "--text", text, *ref_argv)
        case DaedalusProfile():
            return (*prefix, "daedalus", "profile")
    assert_never(request)


def execute_approved(payload: object) -> str:
    """Verify binding, run without a shell, and raise on process failure."""
    request = approved_request(payload)
    command = argv(request)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkerExecutionError("worker timed out after 3600 seconds") from exc
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        detail = output[:2000] or "no process output"
        raise WorkerExecutionError(
            f"worker exited with status {result.returncode}: {detail}"
        )
    return f"[exit 0] {output[:2000]}"
