"""Model router (v2 #1) — task classification + provider-aware model pick."""

from __future__ import annotations

from birkin import router


def test_classify_buckets():
    assert router.classify("fix a typo in the import") == "quick"
    assert router.classify("refactor the auth architecture") == "reason"
    assert router.classify("tweak the button CSS layout") == "visual"
    assert router.classify("write a haiku about the sea") == "default"


def test_pick_model_off_by_default():
    assert router.pick_model({"provider": "claude-cli"}, "refactor this") is None


def test_pick_model_claude_tiers_when_on():
    cfg = {"provider": "claude-cli", "model_routing": True}
    assert router.pick_model(cfg, "fix a typo") == "haiku"
    assert router.pick_model(cfg, "debug the root cause") == "opus"
    assert router.pick_model(cfg, "say hello") == "sonnet"   # default tier


def test_pick_model_routes_override():
    cfg = {"provider": "claude-cli", "model_routing": True,
           "model_routes": {"quick": "haiku-custom"}}
    assert router.pick_model(cfg, "fix a typo") == "haiku-custom"


def test_pick_model_unknown_provider_returns_none_without_routes():
    # We never guess a model name for a provider we don't tier.
    cfg = {"provider": "codex-cli", "model_routing": True}
    assert router.pick_model(cfg, "refactor this") is None
    cfg2 = {"provider": "codex-cli", "model_routing": True,
            "model_routes": {"reason": "gpt-5-codex"}}
    assert router.pick_model(cfg2, "refactor this") == "gpt-5-codex"
