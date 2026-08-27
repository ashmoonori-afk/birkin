from __future__ import annotations

from pathlib import Path

from birkin import approvals, store
from birkin.computer_use.approval_bridge import ApprovalBridge, _grant_path


def test_existing_approval_flow_grants_future_retry_without_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    bridge = ApprovalBridge(session_id="session-a")
    proposed = bridge.propose(
        intent_digest="intent-a",
        prior_receipt="receipt-a",
        action="double_click",
    )

    claimed = approvals.claim(proposed.review_id, approved_by="human:test", approved_via="test")
    executed = approvals.execute_claimed(proposed.review_id)

    assert claimed["ok"] is True
    assert executed["ok"] is True
    assert "grant" in executed["result"].casefold()
    assert (
        bridge.consume(
            proposed.grant_id,
            intent_digest="intent-a",
            prior_receipt="receipt-a",
        )
        is None
    )
    assert (
        bridge.consume(
            proposed.grant_id,
            intent_digest="intent-a",
            prior_receipt="receipt-a",
        )
        == "foreground_approval_expired"
    )


def test_grant_is_session_digest_and_receipt_bound(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    bridge = ApprovalBridge(session_id="session-a")
    proposed = bridge.propose(
        intent_digest="intent-a",
        prior_receipt="receipt-a",
        action="key",
    )
    approvals.claim(proposed.review_id, approved_by="human:test", approved_via="test")
    approvals.execute_claimed(proposed.review_id)

    other_session = ApprovalBridge(session_id="session-b")
    assert (
        other_session.consume(
            proposed.grant_id,
            intent_digest="intent-a",
            prior_receipt="receipt-a",
        )
        == "foreground_approval_mismatch"
    )
    assert (
        bridge.consume(
            proposed.grant_id,
            intent_digest="intent-b",
            prior_receipt="receipt-a",
        )
        == "foreground_approval_mismatch"
    )


def test_tampered_grant_expiry_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    bridge = ApprovalBridge(session_id="session-a")
    proposed = bridge.propose(
        intent_digest="intent-a",
        prior_receipt="receipt-a",
        action="double_click",
    )
    store._write_json(
        _grant_path(proposed.grant_id),
        {
            "state": "approved",
            "session_id": "session-a",
            "intent_digest": "intent-a",
            "prior_receipt": "receipt-a",
            "expires_at": "not-a-datetime",
        },
    )

    assert (
        bridge.consume(
            proposed.grant_id,
            intent_digest="intent-a",
            prior_receipt="receipt-a",
        )
        == "foreground_approval_mismatch"
    )
