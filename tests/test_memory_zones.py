"""VaultMemory ↔ Mnemosyne integration: zone placement, access recording,
zone-aware render, and the new memory tools."""

from __future__ import annotations

from pathlib import Path

from birkin import config, mnemosyne
from birkin.memory import VaultMemory


def _mem() -> VaultMemory:
    return VaultMemory(config.load_config())


def _vault() -> Path:
    return config.vault_dir(config.load_config())


def _tool(m: VaultMemory, name: str):
    return next(t for t in m.tools() if t.name == name)


# ---------------- placement -------------------------------------------------

def test_new_note_lands_in_type_zone():
    m = _mem()
    p = m.write_note("Roadmap", "the plan", note_type="project")
    assert p.parent.name == "projects"
    p2 = m.write_note("Profile - lang", "korean", note_type="preference")
    assert p2.parent.name == "identity"


def test_explicit_zone_overrides_type_map():
    m = _mem()
    p = m.write_note("Budget 2026", "numbers", note_type="fact",
                     zone="finance")
    assert p.parent.name == "finance"


def test_update_never_moves_an_existing_note():
    m = _mem()
    # legacy flat note (inbox = vault root)
    p1 = m.write_note("Legacy", "old world", zone="inbox")
    assert p1.parent == _vault()
    p2 = m.write_note("Legacy", "updated body", note_type="project")
    assert p2 == p1                       # stayed in place despite type zone
    assert "updated body" in m.get_note("Legacy")


def test_get_note_finds_note_inside_zone_dir():
    m = _mem()
    m.write_note("Deep", "inside a zone", note_type="person")
    assert "inside a zone" in m.get_note("Deep")


# ---------------- access recording ------------------------------------------

def test_write_and_get_note_potentiate_but_search_does_not():
    m = _mem()
    m.write_note("Tracked", "observable body")
    s = mnemosyne.slug("Tracked")
    assert m.dex.dynamics_of(s)["access_count"] == 1     # write = access
    m.get_note("Tracked")
    assert m.dex.dynamics_of(s)["access_count"] == 2     # read = access
    m.search("observable")
    assert m.dex.dynamics_of(s)["access_count"] == 2     # browse ≠ access


def test_dynamics_survive_index_rebuild():
    m = _mem()
    m.write_note("Durable", "state outlives cache")
    s = mnemosyne.slug("Durable")
    m.get_note("Durable")
    before = m.dex.dynamics_of(s)["access_count"]
    (_vault() / mnemosyne.INDEX_FILE).unlink()           # kill the cache
    m2 = _mem()
    m2.search("state")                                    # forces rebuild
    assert m2.dex.dynamics_of(s)["access_count"] == before


# ---------------- search facade ----------------------------------------------

def test_search_returns_compat_keys_plus_zone_and_related():
    m = _mem()
    m.write_note("Linked", "target of links")
    m.write_note("Source", "carrot payload", links=["Linked"])
    hits = m.search("carrot")
    assert hits and hits[0]["title"] == "source"          # slug (compat)
    assert "snippet" in hits[0] and hits[0]["zone"]
    assert "linked" in hits[0].get("related", [])


def test_search_korean_via_vaultmemory():
    m = _mem()
    m.write_note("회의 기록", "구역 우선순위 논의")
    hits = m.search("우선순위")
    assert hits and hits[0]["title"] == mnemosyne.slug("회의 기록")


# ---------------- render -----------------------------------------------------

def test_render_orders_identity_first_and_labels_inbox():
    m = _mem()
    m.write_note("Profile - name", "ash", note_type="preference")
    m.write_note("Some Fact", "knowledge item", note_type="fact")
    m.write_note("Loose", "unfiled thing", zone="inbox")
    digest = m.render()
    assert digest.index("identity") < digest.index("knowledge")
    assert "inbox" in digest
    assert "[[Profile - name]]" in digest


def test_render_keeps_polarity_warning():
    m = _mem()
    m.write_note("Bad Path", "this failed before", polarity="negative")
    assert "known failure" in m.render()


def test_render_excludes_archive_zone():
    m = _mem()
    m.write_note("Buried", "archived away")
    m.rezone("Buried", mnemosyne.ARCHIVE_ZONE)
    assert "Buried" not in m.render()


# ---------------- tools -------------------------------------------------------

def test_memory_rezone_tool_moves_note():
    m = _mem()
    m.write_note("Portable", "moves around")
    res = _tool(m, "memory_rezone").fn(
        {"title": "Portable", "zone": "travel"}, None)
    assert not res.is_error
    assert (_vault() / "travel" / "portable.md").is_file()


def test_memory_rezone_tool_reports_errors():
    res = _tool(_mem(), "memory_rezone").fn(
        {"title": "Nope", "zone": "travel"}, None)
    assert res.is_error


def test_memory_related_tool_lists_candidates():
    m = _mem()
    m.write_note("Base", "terraform infrastructure modules")
    m.write_note("Twin", "terraform infrastructure guide")
    res = _tool(m, "memory_related").fn({"title": "Base"}, None)
    assert not res.is_error and "twin" in res.content.lower()


def test_memory_write_note_tool_accepts_zone():
    m = _mem()
    res = _tool(m, "memory_write_note").fn(
        {"title": "Zoned", "body": "b", "zone": "finance"}, None)
    assert not res.is_error
    assert (_vault() / "finance" / "zoned.md").is_file()


# ---------------- maintenance --------------------------------------------------

def test_purge_expired_reaches_zone_subdirectories():
    import re
    m = _mem()
    m.write_note("Ephemeral", "gone soon", note_type="fact", ttl_days=1)
    p = _vault() / "knowledge" / "ephemeral.md"
    text = re.sub(r"expires_at: .+", "expires_at: 2020-01-01",
                  p.read_text(encoding="utf-8"))
    p.write_text(text, encoding="utf-8")
    assert m.purge_expired() == 1
    assert not p.exists()


def test_reindex_returns_stats():
    m = _mem()
    m.write_note("S1", "alpha", note_type="fact")
    m.write_note("S2", "beta", note_type="project")
    stats = m.reindex()
    assert stats["notes"] == 2 and stats["zones"] >= 2
