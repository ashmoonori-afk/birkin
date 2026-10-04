"""Standalone provenance roundtrips and literal legacy frontmatter."""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin_mnemosyne.frontmatter import parse
from birkin_mnemosyne.json_types import JsonValue
from birkin_mnemosyne.memory_format import compose_frontmatter
from birkin_mnemosyne.memory_io import MemoryIO


def compose(sources: list[str]) -> str:
    return compose_frontmatter(
        title="Source record",
        note_type="topic",
        created="2026-01-02",
        updated="2026-01-02",
        confidence=0.7,
        sources=sources,
        tags=["memory"],
    )


@pytest.mark.parametrize(
    "sources",
    [
        ["notes/2026-01-02, morning session"],
        ["notes/2026-01-02, morning session", "plain"],
        ['read "quoted, notes"', "plain"],
        ['a", b', "plain"],
        ["notes/[draft, morning", "plain"],
        ["notes/]draft, morning", "plain"],
        ["both 'single' and \"double\", notes", "plain"],
        ['one\\", two', 'two\\\\", three', 'three\\\\\\", four', "plain"],
        ["C:\\", "\\\\server\\share\\", "plain"],
        ["line\nnext\rpart\tend", "plain"],
        ["split\v\f\x1c\x1d\x1e\x85\u2028\u2029lines", "plain"],
        ["\uba54\ubaa8 \u6f22\u5b57 \U0001f680", "plain"],
        ["", " leading ", "trailing ", "plain"],
        ["plain", "another"],
        [],
    ],
)
def test_sources_survive_repeated_composition(sources: list[str]) -> None:
    # Given: exact source arrays, including following plain-item neighbors.
    current = sources
    for _ in range(3):
        # When: the actual composer and parser roundtrip their sources.
        text = compose(current)
        metadata, body = parse(text)
        # Then: provenance is unchanged, without accumulating escapes.
        assert metadata["sources"] == sources
        assert body == ""
        parsed_sources = metadata["sources"]
        assert isinstance(parsed_sources, list)
        current = [str(item) for item in parsed_sources]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('["a, b", plain]', ["a, b", "plain"]),
        ("['a, b', plain]", ["a, b", "plain"]),
        ('["[a, b", plain]', ["[a, b", "plain"]),
        ("['}a, b', plain]", ["}a, b", "plain"]),
        ('[["a, b", plain], tail]', [["a, b", "plain"], "tail"]),
        ("[['a, b', plain], tail]", [["a, b", "plain"], "tail"]),
        ("['C:\\', 'plain']", ["C:\\", "plain"]),
        ('["C:\\", "plain"]', ["C:\\", "plain"]),
        ("['\\\\server\\share', 'C:\\\\', plain]", ["\\\\server\\share", "C:\\\\", "plain"]),
        ('["\\\\server\\share", "C:\\\\", plain]', ["\\\\server\\share", "C:\\\\", "plain"]),
        ('["a\\"b", plain]', ['a\\"b', "plain"]),
        (r'["\n\t\q\u0041", plain]', [r"\n\t\q\u0041", "plain"]),
        ("['it''s fine', plain]", ["it''s fine", "plain"]),
        ("[someone's notes, plain]", ["someone's notes", "plain"]),
        ('[read "quoted" notes, plain]', ['read "quoted" notes', "plain"]),
        ("[[a, b], plain]", [["a", "b"], "plain"]),
        ("[true, false, null, 2, 0.5, plain]", [True, False, None, 2, 0.5, "plain"]),
        ("[]", []),
        ('"\\\\server\\share\\"', "\\\\server\\share\\"),
        ("'C:\\'", "C:\\"),
    ],
)
def test_legacy_values_keep_literal_quotes_and_paths(
    value: str, expected: JsonValue
) -> None:
    # Given: unmarked legacy values, not JSON escape semantics.
    text = f"---\nkey: {value}\n---\n\nbody\n"
    # When: the standalone parser reads a handwritten note.
    metadata, body = parse(text)
    # Then: quotes contain separators; backslashes remain literal.
    assert metadata["key"] == expected
    assert body == "\nbody"


@pytest.mark.parametrize(
    "fields",
    [
        'sources_encoding: json-v1\nsources: ["a\\", b", "C:\\\\", "plain"]',
        'sources: ["a\\", b", "C:\\\\", "plain"]\nsources_encoding: json-v1',
        'sources_encoding : "json-v1" \nsources : ["a\\", b", "C:\\\\", "plain"]',
        'sources_encoding: other\nsources: ["a\\", b", "C:\\\\", "plain"]\nsources_encoding: json-v1',
    ],
)
def test_marked_sources_decode_complete_json_arrays(fields: str) -> None:
    # Given: independently handwritten escapes and marker positions.
    # When: the actual reader decodes the source-only format.
    metadata, _ = parse(f"---\n{fields}\n---\n")
    # Then: quote/backslash escapes decode exactly once.
    assert metadata["sources"] == ['a", b', "C:\\", "plain"]
    assert metadata["sources_encoding"] == "json-v1"


@pytest.mark.parametrize("value", ['["broken"', '[1, "plain"]', '{"x": 1}', "null", ""])
def test_invalid_marked_sources_remain_raw(value: str) -> None:
    # Given: invalid or wrong-shaped serialized sources with an explicit marker.
    # When: the forgiving parser crosses the serialized-data boundary.
    metadata, _ = parse(f"---\nsources_encoding: json-v1\nsources: {value}\n---\n")
    # Then: malformed data is not reinterpreted as legacy provenance.
    assert metadata["sources"] == value


@pytest.mark.parametrize(
    "marker",
    [
        "",
        "sources_encoding: other\n",
        "  sources_encoding: json-v1\n",
        "sources_encoding: json-v1\nsources_encoding: other\n",
    ],
)
def test_unmarked_or_unknown_sources_keep_literal_escapes(marker: str) -> None:
    # Given: no applicable top-level encoding marker.
    # When: an unmarked source with two literal backslashes is read.
    metadata, _ = parse(f'---\n{marker}sources: ["\\\\server", "plain"]\n---\n')
    # Then: legacy strings are not collapsed by JSON decoding.
    assert metadata["sources"] == ["\\\\server", "plain"]


def test_source_marker_does_not_decode_nested_or_unrelated_values() -> None:
    # Given: a top-level source marker with unrelated and nested legacy values.
    text = (
        '---\nsources_encoding: json-v1\nsources: ["plain"]\n'
        'title: "\\\\server"\nmetadata:\n  sources: ["\\\\server", "plain"]\n---\n'
    )
    # When: frontmatter is parsed.
    metadata, _ = parse(text)
    # Then: only top-level sources use the new codec.
    assert metadata["sources"] == ["plain"]
    assert metadata["title"] == "\\\\server"
    assert metadata["metadata"] == {"sources": ["\\\\server", "plain"]}


def test_composed_sources_stay_on_one_physical_line() -> None:
    # Given: every line separator recognized by str.splitlines and a plain neighbor.
    sources = ["a\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029b", "plain"]
    # When: the actual composer serializes the sources.
    text = compose(sources)
    # Then: no source character can inject a new field or body delimiter.
    lines = text.splitlines()
    assert len(lines) == len(compose(["plain"]).splitlines())
    assert len([line for line in lines if line.startswith("sources: ")]) == 1
    assert parse(text)[0]["sources"] == sources


@pytest.mark.parametrize(
    "source",
    [
        "notes/2026-01-02, morning session",
        'notes/[draft]\\", morning',
        "plain",
    ],
)
def test_memory_write_append_preserves_sources_and_revisions(
    tmp_path: Path, source: str
) -> None:
    # Given: a real vault and the exact create/no-source/dedup/new-source lifecycle.
    memory = MemoryIO({"vault_path": tmp_path})
    stages = [
        ("first", source, [source]),
        ("second", None, [source]),
        ("third", source, [source]),
        ("fourth", "another", [source, "another"]),
    ]
    bodies: list[str] = []
    for revision, (body, added_source, expected) in enumerate(stages, 1):
        # When: MemoryIO writes or appends through real disk and index machinery.
        path = memory.write_note(
            "Source record", body, source=added_source, append=revision > 1
        )
        bodies.append(body)
        # Then: rereading persisted data preserves provenance, body order and version.
        metadata, stored_body = parse(path.read_text(encoding="utf-8"))
        assert metadata["sources"] == expected
        assert metadata["version"] == revision
        assert stored_body.strip() == "\n\n".join(bodies)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('["notes/2026-01-02, morning", "plain"]', ["notes/2026-01-02, morning", "plain"]),
        ('["\\\\server\\share", "C:\\", plain]', ["\\\\server\\share", "C:\\", "plain"]),
        ("['C:\\', plain]", ["C:\\", "plain"]),
        ("[plain, another]", ["plain", "another"]),
    ],
)
def test_append_preserves_intact_unmarked_legacy_sources(
    tmp_path: Path, value: str, expected: list[str]
) -> None:
    # Given: an intact handwritten legacy note, not the new composer.
    memory = MemoryIO({"vault_path": tmp_path})
    seed = tmp_path / "source-record.md"
    _ = seed.write_text(
        f"---\ntitle: Source record\nversion: 1\nsources: {value}\n---\n\nold\n",
        encoding="utf-8",
    )
    # When: a normal append reads and rewrites the existing note.
    path = memory.write_note("Source record", "new", append=True)
    # Then: no legacy backslash/comma is lost during conversion.
    metadata, body = parse(path.read_text(encoding="utf-8"))
    assert path == seed
    assert metadata["sources"] == expected
    assert metadata["version"] == 2
    assert body.strip() == "old\n\nnew"


def test_plain_body_without_frontmatter_is_unchanged() -> None:
    # Given: ordinary body text.
    text = "plain, body\n"
    # When: the actual frontmatter parser reads it.
    metadata, body = parse(text)
    # Then: no metadata is invented.
    assert metadata == {}
    assert body == text
