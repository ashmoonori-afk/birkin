"""Ladder-of-inference evidence gate (design item 3)."""

from __future__ import annotations

from birkin import config, evidence_gate


def test_extract_claims_keeps_factual_sentences() -> None:
    reply = ("All 12 tests passed quickly. I think this is elegant. "
             "Should we refactor next? The fix lives in birkin/agent and "
             "nowhere else.")
    claims = evidence_gate.extract_claims(reply)
    assert any("12 tests passed" in c for c in claims)
    assert any("birkin/agent" in c for c in claims)
    assert not any(c.lower().startswith("i think") for c in claims)
    assert not any(c.endswith("?") for c in claims)


def test_extract_claims_empty_and_opinion_only() -> None:
    assert evidence_gate.extract_claims("") == []
    assert evidence_gate.extract_claims(
        "Maybe 3 ways exist. We should think about it.") == []


def test_verify_reply_supported() -> None:
    reply = "All 12 tests passed quickly."
    outputs = ["collected 12 items\nall 12 tests passed quickly in 0.5s"]
    report = evidence_gate.verify_reply(reply, outputs)
    assert report.checks, "a factual claim should have been extracted"
    assert report.all_supported


def test_verify_reply_unsupported_number_mismatch() -> None:
    reply = "All 15 tests passed quickly."
    outputs = ["collected 12 items\nall 12 tests passed quickly in 0.5s"]
    report = evidence_gate.verify_reply(reply, outputs)
    assert report.unsupported


def test_verify_reply_no_outputs_is_unsupported() -> None:
    report = evidence_gate.verify_reply("All 12 tests passed quickly.", [])
    assert report.checks
    assert not report.all_supported


def test_collect_tool_outputs_shapes() -> None:
    messages = [
        {"role": "assistant", "content": "just text"},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "a",
             "content": "string output"},
            {"type": "tool_result", "tool_use_id": "b", "content": [
                {"type": "text", "text": "block output"},
                {"type": "image", "data": "ignored"},
            ]},
            {"type": "text", "text": "not a tool result"},
        ]},
        "not a dict",
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c", "content": "   "},
        ]},
    ]
    outputs = evidence_gate.collect_tool_outputs(messages)
    assert outputs == ["string output", "block output"]


def test_annotate_appends_ascii_footer() -> None:
    report = evidence_gate.verify_reply(
        "All 15 tests passed quickly.", ["all 12 tests passed"])
    out = evidence_gate.annotate("body text", report, threshold=0)
    assert out.startswith("body text")
    footer = out[len("body text"):]
    assert footer.isascii()
    assert "unverified: 1 claim(s) lack session evidence" in out


def test_annotate_below_threshold_unchanged() -> None:
    report = evidence_gate.verify_reply(
        "All 12 tests passed quickly.",
        ["all 12 tests passed quickly"])
    assert evidence_gate.annotate("body", report, threshold=0) == "body"


def test_default_is_off() -> None:
    assert config.DEFAULT_CONFIG["evidence_gate_enabled"] is False
