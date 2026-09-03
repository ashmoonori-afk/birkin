"""A corrupt stored proposal must be retired, not left pending with dead buttons."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from birkin import config, store
from birkin.gateway import workflow


def _queued(chat_id: str) -> str:
    proposal = workflow.WorkflowProposal(
        title="title",
        summary="summary",
        steps=("step one",),
    )
    return workflow.queue_proposal(proposal, "do the thing", chat_id)


def test_corrupt_payload_resolves_to_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a pending workflow whose payload was clobbered into a non-mapping.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    aid = _queued("42")
    path = config.pending_dir() / f"{aid}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["payload"] = "corrupted"
    _ = path.write_text(json.dumps(record), encoding="utf-8")

    # When: the operator taps approve.
    resolution = workflow.resolve_proposal(
        aid,
        "42",
        approve=True,
        actor_id="human:telegram:42",
        via="gateway:telegram",
    )

    # Then: it is reported as damaged and stops being pending.
    assert "손상" in resolution.message
    assert resolution.resume_prompt is None
    resolved = store.get_pending(aid)
    assert resolved is not None
    assert resolved["status"] == "error"
