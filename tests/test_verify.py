"""Osiris (v2 #3) — verification prompt + verdict parsing + runner."""

from __future__ import annotations

from birkin import verify


def test_build_prompt_includes_item_and_acceptance():
    p = verify.build_prompt("did the thing", "the thing is done")
    assert "[Osiris]" in p and "did the thing" in p and "the thing is done" in p
    assert "VERDICT: PASS" in p and "VERDICT: FAIL" in p


def test_parse_verdict_pass_fail_and_unsure():
    assert verify.parse_verdict("VERDICT: PASS\nlooks good")["passed"] is True
    assert verify.parse_verdict("VERDICT: FAIL\nmissing tests")["passed"] is False
    assert verify.parse_verdict("hmm, maybe")["passed"] is False   # unsure -> FAIL


def test_verify_runs_ask_and_is_conservative_on_error():
    assert verify.verify(lambda p: "VERDICT: PASS\nok", "x")["passed"] is True
    assert verify.verify(lambda p: "VERDICT: FAIL\nno", "x")["passed"] is False

    def boom(_p):
        raise RuntimeError("verifier down")
    res = verify.verify(boom, "x")
    assert res["passed"] is False and "error" in res["reason"]
