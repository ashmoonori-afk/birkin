"""Boulder (v2 #5) — resumable checkbox-plan state."""

from __future__ import annotations

from birkin import boulder


def test_create_next_remaining_and_check_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    d = boulder.create("build a CRM", [
        {"title": "schema", "acceptance": "tables exist"},
        "api endpoints",
    ])
    assert d["total"] == 2 and d["done"] == 0 and d["remaining"] == 2
    assert d["next_index"] == 0 and d["active"] is True

    d1 = boulder.check(d["slug"], 0, verdict="PASS schema")
    assert d1["done"] == 1 and d1["remaining"] == 1 and d1["next_index"] == 1
    assert d1["active"] is True

    d2 = boulder.check(d["slug"], 1, verdict="PASS api")
    assert d2["done"] == 2 and d2["remaining"] == 0 and d2["next_index"] is None
    assert d2["active"] is False          # goal complete -> inactive


def test_create_resumes_not_clobbers(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    boulder.create("ship landing page", ["a", "b", "c"])
    boulder.check(boulder.create("ship landing page", []).get("slug") or "x", 0)
    # re-create the SAME goal -> resume (keeps the 3 steps + the check), no wipe
    again = boulder.create("ship landing page", ["DIFFERENT"])
    assert again["resumed"] is True and again["total"] == 3 and again["done"] == 1


def test_create_rejects_empty_steps(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    import pytest
    with pytest.raises(ValueError):
        boulder.create("a goal with no steps", [])      # no zombie plan


def test_create_ignores_caller_done_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    # A caller cannot smuggle in a pre-checked step (bypassing the Osiris gate).
    d = boulder.create("goal", [{"title": "a", "done": True, "verdict": "fake"}])
    assert d["done"] == 0 and d["remaining"] == 1 and d["next_index"] == 0


def test_active_lists_only_unfinished(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    boulder.create("goal one", ["x"])
    d = boulder.create("goal two", ["y"])
    boulder.check(d["slug"], 0)           # goal two complete -> inactive
    slugs = {b["slug"] for b in boulder.active()}
    assert any("goal-one" in s for s in slugs)
    assert not any("goal-two" in s for s in slugs)


def test_korean_goals_get_distinct_resumable_plans(tmp_path, monkeypatch):
    """boulder.create slugs through neurosis._slug, so it inherited the
    ASCII-only bug: two unrelated Korean goals raised in the same second
    collapsed onto one slug, and create() returns an existing active plan
    unchanged — silently handing the user someone else's checklist.
    """
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    a = boulder.create("배포 파이프라인 정리", ["파악", "수정"])
    b = boulder.create("문서 번역 작업", ["초벌", "검수"])

    assert a["slug"] != b["slug"]
    assert a["slug"] == "배포-파이프라인-정리"
    assert boulder.load(b["slug"])["steps"][0]["title"] == "초벌"

    # The same goal still resumes rather than duplicating.
    again = boulder.create("배포 파이프라인 정리", ["다른", "단계"])
    assert again["slug"] == a["slug"]
    assert boulder.load(a["slug"])["steps"][0]["title"] == "파악"
