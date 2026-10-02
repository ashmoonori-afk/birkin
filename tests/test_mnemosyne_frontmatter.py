"""Regression tests for quoted inline-list frontmatter round trips.

A source string such as ``"notes/2026-01-02, morning session"`` used to be
split in two by the inline-list tokenizer, because ``_split_commas`` tracked
bracket depth but not quoted-token state. ``MemoryIO.write_note`` then fed the
corrupted items back through the composer on the next write.
"""

from __future__ import annotations

from pathlib import Path

from birkin_mnemosyne.frontmatter import parse
from birkin_mnemosyne.memory_format import compose_frontmatter
from birkin_mnemosyne.memory_io import MemoryIO

COMMA_SOURCE = "notes/2026-01-02, morning session"

MULTI_SOURCES = [
    COMMA_SOURCE,
    'quote " then, comma',
    "unmatched ] and } brackets",
    'backslash \\ right next to " a quote',
    "  padded  ",
]


def _compose(sources: list[str], tags: list[str] | None = None) -> str:
    return compose_frontmatter(
        title="Round trip",
        note_type="topic",
        created="2026-01-02",
        updated="2026-01-02",
        confidence=0.7,
        sources=sources,
        tags=tags if tags is not None else [],
    )


def test_source_strings_round_trip() -> None:
    text = _compose(MULTI_SOURCES)
    metadata, _body = parse(text)
    assert metadata["sources"] == MULTI_SOURCES


def test_single_quoted_comma_string_is_one_value() -> None:
    metadata, _body = parse("---\ntitle: t\nkey: ['notes/a, b', 'plain']\n---\nbody\n")
    assert metadata["key"] == ["notes/a, b", "plain"]


def test_scalar_quoted_values_still_unquote() -> None:
    metadata, _body = parse(
        "---\ntitle: \"hello, world\"\nother: 'it''s fine'\n---\n"
    )
    assert metadata["title"] == "hello, world"
    assert metadata["other"] == "it''s fine"


def test_bare_apostrophe_is_not_a_quote_boundary() -> None:
    metadata, _body = parse("---\ntitle: it's fine, really\ncount: 3\n---\n")
    assert metadata["title"] == "it's fine, really"
    assert metadata["count"] == 3


def test_nested_inline_lists_keep_depth_semantics() -> None:
    metadata, _body = parse("---\nkey: [[a, b], [c, d]]\n---\n")
    assert metadata["key"] == [["a", "b"], ["c", "d"]]


def test_escaped_double_quote_and_backslash_decode() -> None:
    text = _compose(['say "hi" \\ now'])
    metadata, _body = parse(text)
    assert metadata["sources"] == ['say "hi" \\ now']


def test_unrecognized_backslash_escape_is_preserved() -> None:
    metadata, _body = parse('---\nkey: "back\\slash"\nother: "\\n literal"\n---\n')
    assert metadata["key"] == "back\\slash"
    assert metadata["other"] == "\\n literal"


def test_plain_scalar_values_unchanged() -> None:
    metadata, _body = parse(
        "---\ntitle: plain\ncount: 3\nratio: 1.5\nflag: true\nnothing: null\n---\n"
    )
    assert metadata["title"] == "plain"
    assert metadata["count"] == 3
    assert metadata["ratio"] == 1.5
    assert metadata["flag"] is True
    assert metadata["nothing"] is None


def test_write_note_preserves_quoted_source_on_append(tmp_path: Path) -> None:
    memory = MemoryIO({"vault_path": tmp_path / "vault"})
    path = memory.write_note("Quoted source", "first", source=COMMA_SOURCE)
    memory.write_note("Quoted source", "second", append=True)
    memory.write_note("Quoted source", "third", source=COMMA_SOURCE, append=True)

    metadata, body = parse(path.read_text(encoding="utf-8"))
    assert metadata["sources"] == [COMMA_SOURCE]
    assert "first" in body
    assert "second" in body
    assert "third" in body
