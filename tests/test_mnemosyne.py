"""Mnemosyne — the mechanical memory engine (index / BM25 / dynamics / zones).

Pure functions get exact-value tests; the engine is exercised against a real
temp vault (isolated BIRKIN_HOME via conftest). No LLM anywhere.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from birkin import config, mnemosyne
from birkin.memory import VaultMemory


def _vault() -> Path:
    return config.vault_dir(config.load_config())


def _mem() -> VaultMemory:
    return VaultMemory(config.load_config())


def _engine() -> mnemosyne.Mnemosyne:
    eng = mnemosyne.Mnemosyne(_vault())
    eng.refresh()
    return eng


NOW = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)


# ---------------- tokenize -------------------------------------------------

def test_tokenize_ascii_words_lowercased():
    assert mnemosyne.tokenize("Hello World2") == ["hello", "world2"]


def test_tokenize_hangul_runs_and_bigrams():
    toks = mnemosyne.tokenize("메모리 시스템")
    assert "메모리" in toks and "시스템" in toks
    assert "메모" in toks and "모리" in toks          # bigrams of run 1
    assert "시스" in toks and "스템" in toks          # bigrams of run 2


def test_tokenize_mixed_korean_ascii():
    toks = mnemosyne.tokenize("AI에이전트")
    assert "ai" in toks and "에이전트" in toks and "이전" in toks


# ---------------- BM25 ------------------------------------------------------

def test_bm25_length_normalization_hand_computed():
    """Hand-computed against k1=0.9, b=0.5 with an idf^1 query weight.

    The query weight makes each term contribute idf**2 (query side × document
    side), which is what ranking-v2 measured as the win (ADR-043).
    """
    import math
    k1, b = mnemosyne.K1, mnemosyne.B
    postings = {"cat": {"d1": 2, "d2": 1}, "dog": {"d1": 1}}
    doclens = {"d1": 3, "d2": 1}
    scores = mnemosyne.bm25_scores(["cat"], postings, doclens,
                                   avgdl=2.0, n_docs=2)
    idf = math.log(1 + 0.5 / 2.5)

    def expect(tf, dl):
        denom = tf + k1 * (1 - b + b * dl / 2.0)
        return idf * idf * tf * (k1 + 1) / denom

    assert scores["d1"] == pytest.approx(expect(2, 3))
    assert scores["d2"] == pytest.approx(expect(1, 1))


def test_bm25_shorter_document_wins_at_equal_term_frequency():
    """Length normalization: same tf, shorter document scores higher.

    The old form of this check compared tf=2/len=3 against tf=1/len=1 and
    relied on b=0.75 normalizing hard enough for the shorter doc to win — a
    property of that tuning, not of BM25. Holding tf equal tests the
    invariant itself, so it survives a retune.
    """
    postings = {"cat": {"short": 1, "long": 1}}
    doclens = {"short": 1, "long": 20}
    scores = mnemosyne.bm25_scores(["cat"], postings, doclens,
                                   avgdl=10.5, n_docs=2)
    assert scores["short"] > scores["long"]


def test_bm25_query_weight_favours_the_rare_term():
    """A rare query term must outweigh a term that is in every document."""
    postings = {"common": {"d1": 5, "d2": 5, "d3": 5}, "rare": {"d2": 1}}
    doclens = {"d1": 6, "d2": 6, "d3": 6}
    scores = mnemosyne.bm25_scores(["common", "rare"], postings, doclens,
                                   avgdl=6.0, n_docs=3)
    assert max(scores, key=lambda s: scores[s]) == "d2"


def test_bm25_unknown_terms_yield_empty():
    assert mnemosyne.bm25_scores(["zzz"], {}, {}, 1.0, 0) == {}


# ---------------- dynamics (pure) ------------------------------------------

def test_effective_strength_decays_on_ebbinghaus_curve():
    import math
    dyn = {"strength": 1.0, "stability": 7.0, "access_count": 1,
           "last_access": (NOW - timedelta(days=7)).isoformat()}
    eff = mnemosyne.effective_strength(dyn, NOW)
    assert eff == pytest.approx(math.exp(-1.0))


def test_effective_strength_never_below_floor():
    dyn = {"strength": 1.0, "stability": 7.0, "access_count": 1,
           "last_access": (NOW - timedelta(days=1000)).isoformat()}
    assert mnemosyne.effective_strength(dyn, NOW) == mnemosyne.EFF_FLOOR


def test_effective_strength_fresh_equals_strength():
    dyn = {"strength": 2.0, "stability": 7.0, "access_count": 1,
           "last_access": NOW.isoformat()}
    assert mnemosyne.effective_strength(dyn, NOW) == pytest.approx(2.0)


def test_potentiate_returns_new_dict_and_bumps_strength():
    dyn = {"strength": 1.0, "stability": 7.0, "access_count": 0,
           "last_access": (NOW - timedelta(minutes=5)).isoformat()}
    out = mnemosyne.potentiate(dyn, NOW)
    assert out is not dyn and dyn["strength"] == 1.0     # immutability
    assert out["strength"] == pytest.approx(1.25)
    assert out["access_count"] == 1
    assert out["last_access"] == NOW.isoformat()


def test_potentiate_spacing_gate_blocks_stability_growth_under_1h():
    dyn = {"strength": 1.0, "stability": 7.0, "access_count": 0,
           "last_access": (NOW - timedelta(minutes=30)).isoformat()}
    assert mnemosyne.potentiate(dyn, NOW)["stability"] == pytest.approx(7.0)


def test_potentiate_spaced_access_multiplies_stability():
    dyn = {"strength": 1.0, "stability": 7.0, "access_count": 0,
           "last_access": (NOW - timedelta(hours=2)).isoformat()}
    assert mnemosyne.potentiate(dyn, NOW)["stability"] == pytest.approx(10.5)


def test_potentiate_caps():
    dyn = {"strength": 1.0, "stability": 7.0, "access_count": 0,
           "last_access": (NOW - timedelta(hours=2)).isoformat()}
    for i in range(40):
        dyn = mnemosyne.potentiate(
            dyn, NOW + timedelta(hours=2 * (i + 1)))
    assert dyn["strength"] == mnemosyne.STRENGTH_CAP
    assert dyn["stability"] <= mnemosyne.STABILITY_CAP


def test_zone_ema_daily_decay():
    ema = mnemosyne.decayed_ema(10.0, "2026-06-30", date(2026, 7, 2))
    assert ema == pytest.approx(10.0 * 0.9 ** 2)


# ---------------- index build / refresh ------------------------------------

def test_index_builds_from_vault_and_maps_zones():
    m = _mem()
    m.write_note("Proj X", "the flagship project", note_type="project")
    m.write_note("Fact Y", "a durable fact", note_type="fact")
    eng = _engine()
    px = eng.note_meta("proj-x")
    assert px is not None and px["zone"] == "projects"
    assert eng.note_meta("fact-y")["zone"] == "knowledge"


def test_incremental_refresh_reparses_only_changed_files(monkeypatch):
    m = _mem()
    m.write_note("A", "alpha body")
    m.write_note("B", "beta body")
    m.write_note("C", "gamma body")
    eng = _engine()                      # full build done

    parsed: list[str] = []
    orig = mnemosyne._note_entry

    def counting(path, rel):
        parsed.append(rel)
        return orig(path, rel)

    monkeypatch.setattr(mnemosyne, "_note_entry", counting)
    # grow one file so (mtime, size) fingerprint definitely changes
    p = _vault() / eng.resolve_rel("b")
    p.write_text(p.read_text(encoding="utf-8") + "\nmore beta text",
                 encoding="utf-8")
    eng.refresh()
    assert parsed and all("b.md" in r for r in parsed)
    assert len(parsed) == 1


def test_corrupted_index_file_triggers_clean_rebuild():
    m = _mem()
    m.write_note("Solid", "still here")
    (_vault() / mnemosyne.INDEX_FILE).write_text("{not json",
                                                 encoding="utf-8")
    eng = _engine()
    assert eng.note_meta("solid") is not None


def test_deleted_note_is_pruned_on_refresh():
    m = _mem()
    m.write_note("Ghost", "soon gone")
    eng = _engine()
    (_vault() / eng.resolve_rel("ghost")).unlink()
    eng.refresh()
    assert eng.note_meta("ghost") is None


# ---------------- search ----------------------------------------------------

def test_search_relevance_dominates():
    m = _mem()
    m.write_note("Pizza", "recipe for pizza dough and toppings")
    m.write_note("Taxes", "annual tax filing checklist")
    eng = _engine()
    hits = eng.search("pizza dough", now=NOW)
    assert hits and hits[0]["slug"] == "pizza"


def test_search_warm_note_outranks_cold_at_equal_relevance():
    m = _mem()
    m.write_note("Alpha", "python tips collected")
    m.write_note("Beta", "python tips collected")
    eng = _engine()
    for i in range(3):
        eng.record_access("beta", now=NOW + timedelta(hours=2 * i))
    hits = eng.search("python tips", now=NOW + timedelta(hours=6))
    assert [h["slug"] for h in hits[:2]] == ["beta", "alpha"]


def test_search_zone_filter_and_archive_exclusion():
    m = _mem()
    m.write_note("Keep", "shared keyword banana", note_type="project")
    m.write_note("Gone", "shared keyword banana", note_type="fact")
    eng = _engine()
    eng.rezone("gone", mnemosyne.ARCHIVE_ZONE)
    hits = eng.search("banana", now=NOW)
    assert [h["slug"] for h in hits] == ["keep"]
    hits_all = eng.search("banana", now=NOW, include_archive=True)
    assert {h["slug"] for h in hits_all} == {"keep", "gone"}
    scoped = eng.search("banana", now=NOW, zone="projects")
    assert [h["slug"] for h in scoped] == ["keep"]


def test_search_korean_query_roundtrip():
    m = _mem()
    m.write_note("메모리 설계", "구역 기반 저장과 인덱스")
    eng = _engine()
    assert eng.search("구역", now=NOW)[0]["slug"] == _slug_kr()


def _slug_kr() -> str:
    from birkin.mnemosyne import slug
    return slug("메모리 설계")


# ---------------- related / stale / rezone ----------------------------------

def test_related_excludes_self_and_existing_links():
    m = _mem()
    m.write_note("Hub", "kubernetes cluster operations",
                 links=["Spoke One"])
    m.write_note("Spoke One", "kubernetes cluster notes")
    m.write_note("Spoke Two", "kubernetes cluster deep dive")
    eng = _engine()
    rel = eng.related("hub")
    slugs = [h["slug"] for h in rel]
    assert "spoke-two" in slugs
    assert "hub" not in slugs and "spoke-one" not in slugs


def test_stale_lists_old_low_strength_notes_but_not_identity():
    m = _mem()
    m.write_note("Old Project", "dusty", note_type="project")
    m.write_note("Me", "the user", note_type="preference")   # → identity
    eng = _engine()
    old = {"strength": 1.0, "stability": 7.0, "access_count": 1,
           "last_access": (NOW - timedelta(days=200)).isoformat()}
    eng.set_dynamics("old-project", old)
    eng.set_dynamics("me", dict(old))
    stale = eng.stale(now=NOW)
    slugs = [s["slug"] for s in stale]
    assert "old-project" in slugs and "me" not in slugs


def test_rezone_moves_file_and_updates_index():
    m = _mem()
    m.write_note("Mover", "goes places", note_type="fact")
    eng = _engine()
    eng.rezone("mover", "finance")
    assert eng.note_meta("mover")["zone"] == "finance"
    assert (_vault() / "finance" / "mover.md").is_file()
    assert not (_vault() / "knowledge" / "mover.md").exists()


def test_rezone_refuses_existing_destination_collision(monkeypatch):
    m = _mem()
    m.write_note("Collision", "source body", note_type="fact")
    source = _vault() / "knowledge" / "collision.md"
    eng = _engine()
    monkeypatch.setattr(eng, "refresh", lambda: None)
    target = _vault() / "finance" / "collision.md"
    target.parent.mkdir(parents=True)
    target.write_text("destination body", encoding="utf-8")

    with pytest.raises(FileExistsError):
        eng.rezone("collision", "finance")

    assert "source body" in source.read_text(encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "destination body"


def test_rezone_refuses_destination_created_after_precheck(monkeypatch):
    m = _mem()
    m.write_note("Racing", "source body", note_type="fact")
    source = _vault() / "knowledge" / "racing.md"
    eng = _engine()
    target = _vault() / "finance" / "racing.md"
    real_link = mnemosyne.os.link
    real_replace = mnemosyne.os.replace

    def create_then_link(old, new):
        target.write_text("racing destination", encoding="utf-8")
        return real_link(old, new)

    def create_then_replace(old, new):
        target.write_text("racing destination", encoding="utf-8")
        return real_replace(old, new)

    monkeypatch.setattr(mnemosyne.os, "link", create_then_link)
    monkeypatch.setattr(mnemosyne.os, "replace", create_then_replace)

    with pytest.raises(FileExistsError):
        eng.rezone("racing", "finance")

    assert "source body" in source.read_text(encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "racing destination"


def test_rezone_rejects_bad_zone_names():
    m = _mem()
    m.write_note("Fixed", "immovable")
    eng = _engine()
    with pytest.raises(ValueError):
        eng.rezone("fixed", "../escape")
    with pytest.raises(ValueError):
        eng.rezone("no-such-note", "finance")


def test_entries_returns_snapshot_not_live_dict():
    """Consumers iterate entries() while other threads mutate the index —
    it must be a copy (review finding: RuntimeError under concurrency)."""
    m = _mem()
    m.write_note("Snap", "frozen view")
    eng = _engine()
    snap = eng.entries()
    snap.clear()                       # vandalize the copy
    assert eng.note_meta("snap") is not None


def test_zone_priority_reflects_access_concentration():
    m = _mem()
    m.write_note("P1", "project work", note_type="project")
    m.write_note("K1", "fact work", note_type="fact")
    eng = _engine()
    for i in range(4):
        eng.record_access("p1", now=NOW + timedelta(hours=2 * i))
    pri = eng.zone_priorities(today=NOW.date())
    assert pri["projects"] == pytest.approx(1.0)
    assert pri.get("knowledge", 0.0) < 1.0


# ---------------- temporal prior -------------------------------------------

def test_temporal_target_korean_cues():
    from datetime import datetime
    now = datetime(2026, 7, 25, 12, 0)
    for cue, days in [("지난주에 정리한 배포 노트", 7), ("어제 쓴 메모", 1),
                      ("지난달 회고", 30), ("3일 전에 만든 계획", 3),
                      ("2주 전 아이디어", 14), ("작년 목표", 365)]:
        got = mnemosyne.temporal_target(cue, now)
        assert got is not None, f"{cue!r} not parsed"
        assert abs((now - got[0]).days - days) <= 1, cue


def test_temporal_target_english_cues_still_work():
    from datetime import datetime
    now = datetime(2026, 7, 25, 12, 0)
    assert mnemosyne.temporal_target("yesterday's note", now) is not None
    assert mnemosyne.temporal_target("3 weeks ago", now) is not None


def test_temporal_target_is_none_without_a_cue():
    from datetime import datetime
    now = datetime(2026, 7, 25, 12, 0)
    assert mnemosyne.temporal_target("배포 파이프라인 정리", now) is None
    assert mnemosyne.temporal_target("kubernetes ingress", now) is None


def test_search_prefers_the_note_from_the_named_week(tmp_path):
    """Two notes, same words, different dates: the temporal cue decides."""
    from datetime import datetime, timedelta, timezone
    vault = tmp_path / "vault"
    (vault / "knowledge").mkdir(parents=True)
    now = datetime.now(timezone.utc)
    for name, when in (("recent", now - timedelta(days=7)),
                       ("ancient", now - timedelta(days=400))):
        (vault / "knowledge" / f"{name}.md").write_text(
            f"---\ntitle: {name}\nupdated: {when.date().isoformat()}\n---\n\n"
            "배포 파이프라인 정리 회의 기록\n", encoding="utf-8")
    m = mnemosyne.Mnemosyne(vault)
    m.refresh()

    plain = [h["slug"] for h in m.search("배포 파이프라인", limit=5)]
    assert set(plain) == {"recent", "ancient"}

    cued = [h["slug"] for h in m.search("지난주 배포 파이프라인", limit=5)]
    assert cued[0] == "recent", f"temporal cue ignored: {cued}"
