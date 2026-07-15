from birkin import config
from birkin.memory import VaultMemory


def _mem():
    return VaultMemory(config.load_config())


def test_write_and_get_note_roundtrip():
    m = _mem()
    m.write_note("FlowerPlus GTM", "Corporate welfare flowers.", note_type="project")
    text = m.get_note("FlowerPlus GTM")
    assert text is not None
    assert "Corporate welfare flowers." in text
    assert "type: project" in text


def test_search_finds_by_keyword():
    m = _mem()
    m.write_note("Topic A", "alpha beta gamma", note_type="topic")
    m.write_note("Topic B", "delta epsilon", note_type="topic")
    hits = m.search("gamma")
    assert any("topic-a" == h["title"] for h in hits)


def test_add_link():
    m = _mem()
    m.write_note("A", "body a")
    m.write_note("B", "body b")
    assert m.add_link("A", "B") is True
    assert "[[B]]" in (m.get_note("A") or "")


def test_add_link_preserves_note_metadata():
    m = _mem()
    p = m.write_note("Tagged A", "body a", note_type="project",
                     tags=["keep"], confidence=0.9, ttl_days=14,
                     source="manual")
    m.write_note("B", "body b")

    assert m.add_link("Tagged A", "B") is True

    text = p.read_text(encoding="utf-8")
    assert "[[B]]" in text
    assert "type: project" in text
    assert "tags: [keep]" in text
    assert "confidence: 0.9" in text
    assert "expires_at:" in text


def test_render_digest_lists_notes():
    m = _mem()
    m.write_note("Note One", "first", note_type="fact")
    digest = m.render()
    assert "[[Note One]]" in digest


def test_list_notes_counts():
    m = _mem()
    m.write_note("N1", "x")
    m.write_note("N2", "y")
    titles = {n["title"] for n in m.list_notes()}
    assert {"N1", "N2"} <= titles


def test_get_missing_note_returns_none():
    assert _mem().get_note("does-not-exist") is None
