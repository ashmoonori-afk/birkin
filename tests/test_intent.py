"""IntentGate (v2 #4) — keyword intent classification."""

from __future__ import annotations

from birkin import intent


def test_classify_modes():
    assert intent.classify("ultrawork: ship the export feature") == "ultrawork"
    assert intent.classify("ulw build the CRM") == "ultrawork"
    assert intent.classify("/neurosis plan the campaign") == "plan"
    assert intent.classify("search the web for pricing") == "search"
    assert intent.classify("analyze this module") == "analyze"
    assert intent.classify("what time is it?") == "normal"


def test_priority_ultrawork_wins():
    assert intent.classify("ultrawork and also analyze it") == "ultrawork"


def test_is_goal_cycle():
    assert intent.is_goal_cycle("ulw do the migration") is True
    assert intent.is_goal_cycle("just answer this") is False
