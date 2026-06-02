"""Blind A/B model compare (odysseus 'Compare', lightweight)."""

from __future__ import annotations

from birkin import compare


def test_compare_runs_both_models_unshuffled():
    asked = []

    def ask(m):
        asked.append(m)
        return f"answer from {m}"

    res = compare.run({}, "q", "opus", "sonnet", ask=ask, shuffle=False)
    assert res["A"]["model"] == "opus" and res["B"]["model"] == "sonnet"
    assert res["A"]["text"] == "answer from opus"
    assert set(asked) == {"opus", "sonnet"}


def test_compare_shuffle_still_covers_both_models():
    res = compare.run({}, "q", "opus", "haiku", ask=lambda m: m, shuffle=True)
    assert {res["A"]["model"], res["B"]["model"]} == {"opus", "haiku"}
    assert res["prompt"] == "q"


def test_default_pair_picks_complementary_tier():
    assert compare.default_pair({"model": "opus"}, None, None) == ("opus", "sonnet")
    assert compare.default_pair({"model": "sonnet"}, None, None) == ("sonnet", "haiku")
    assert compare.default_pair({}, "x", "y") == ("x", "y")        # explicit wins
    assert compare.default_pair({}, None, None)[0] == "opus"       # default model A
