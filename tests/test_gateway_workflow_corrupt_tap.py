"""The Approve button must reach the corrupt-proposal recovery, not fall
through to the generic approval path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from birkin import config, store
from birkin.gateway import workflow
from birkin.gateway.channels.telegram import TelegramChannel


def test_approve_tap_retires_a_corrupt_proposal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a pending workflow whose payload was clobbered into a non-mapping.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    proposal = workflow.WorkflowProposal(
        title="title",
        summary="summary",
        steps=("step one",),
    )
    aid = workflow.queue_proposal(proposal, "do the thing", "42")
    path = config.pending_dir() / f"{aid}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["payload"] = "corrupted"
    _ = path.write_text(json.dumps(record), encoding="utf-8")

    channel = TelegramChannel(
        "tok", allowed_chat_ids=["42"], allowed_sender_ids=[], stream=False
    )
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_call(
        method: str, params: dict[str, object], *_a: object, **_k: object
    ) -> dict[str, object]:
        calls.append((method, params))
        return {"ok": True}

    channel._call = fake_call  # pyright: ignore[reportAttributeAccessIssue]

    # When: the operator taps approve.
    channel._handle_callback(
        object(),  # pyright: ignore[reportArgumentType]
        {
            "id": "cb",
            "data": f"apv:{aid}",
            "from": {"id": 42},
            "message": {
                "chat": {"id": 42, "type": "private"},
                "message_id": 7,
                "text": "x",
            },
        },
    )

    # Then: the tap is answered with the damage notice and the record retires.
    answers = [
        str(params.get("text", ""))
        for method, params in calls
        if method == "answerCallbackQuery"
    ]
    assert any("손상" in text for text in answers), calls
    resolved = store.get_pending(aid)
    assert resolved is not None
    assert resolved["status"] == "error"
