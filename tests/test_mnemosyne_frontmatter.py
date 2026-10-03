"""Round-trip and compatibility tests for the standalone Mnemosyne frontmatter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from birkin_mnemosyne.frontmatter import _parse_value, parse
from birkin_mnemosyne.memory_format import compose_frontmatter
from birkin_mnemosyne.memory_io import MemoryIO

BS = chr(92)
QUOTE = chr(34)
APOS = chr(39)
EACUTE = chr(233)
IDIAERESIS = chr(239)

MARKER = "sources_encoding: json-v1"

COMMA_SOURCE = "notes/2026-01-02, morning session"
MIXED_SOURCE = 'a"b, c\\d'
DRIVE_ROOT = "C:" + BS
UNC_ROOT = BS * 2 + "server" + BS + "share"


def compose(sources: list[str]) -> str:
    return compose_frontmatter(
        title="Round trip",
        note_type="topic",
        created="2026-01-02",
        updated="2026-01-02",
        confidence=0.7,
        sources=sources,
        tags=[],
    )


def composed_sources(sources: list[str]) -> list[str]:
    value = parse(compose(sources))[0]["sources"]
    assert isinstance(value, list)
    return [str(item) for item in value]


def parsed_value(raw: str) -> object:
    return _parse_value(raw)


# --------------------------------------------------------------------------
# Defect regressions: these fail against the unchanged base implementation.
# --------------------------------------------------------------------------


def test_composed_comma_source_round_trips() -> None:
    assert composed_sources([COMMA_SOURCE]) == [COMMA_SOURCE]


def test_composed_comma_source_before_plain_round_trips() -> None:
    assert composed_sources([COMMA_SOURCE, "plain"]) == [COMMA_SOURCE, "plain"]


@pytest.mark.parametrize(
    "sources",
    [
        ["notes/a, b"],
        ['quoted "comma", here'],
        ["'single' , double"],
        ['"quotes, immediately" before comma'],
        ["path [with, unmatched bracket"],
        ["path {with, unmatched brace"],
        ["[bracketed, value]"],
        ['{"json-like": "value, with comma"}'],
        ["'nested single, value'"],
        ['"nested double, value"'],
        ['"mixed \'quote, kinds"'],
        ["'mixed \"quote, kinds'"],
        ["one, two, three"],
        ["comma at end,"],
        [",comma at start"],
        ["tab\tseparated, value"],
        ["unicode caf" + EACUTE + ", na" + IDIAERESIS + "ve"],
        ["line\nseparator, value"],
        ["carriage\rreturn, value"],
        ["line\u2028separator, value"],
        ["para\u2029separator, value"],
    ],
)
def test_composed_sources_round_trip_exactly(sources: list[str]) -> None:
    assert composed_sources(sources) == sources


@pytest.mark.parametrize(
    "sources",
    [
        ['a"b, c' + BS + "d"],
        ["quote" + BS + " before, comma"],
        ["one" + BS + ' before"quote'],
        ["two" + BS * 2 + ' before"quote'],
        ["three" + BS * 3 + ' before"quote'],
        [BS * 2 + "server" + BS + "share, folder"],
        ["C:" + BS + "folder" + BS + ", trailing"],
        ["mixed 'single' and \"double\", with backslash " + BS],
    ],
)
def test_composed_mixed_sources_round_trip_and_are_stable(sources: list[str]) -> None:
    first = composed_sources(sources)
    assert first == sources
    assert composed_sources(first) == sources


def test_repeated_round_trips_do_not_grow_escapes() -> None:
    expected = ['a"b, c' + BS + "d", UNC_ROOT, "plain, tail"]
    value = list(expected)
    for _ in range(5):
        value = composed_sources(value)
    assert value == expected


@pytest.mark.parametrize(
    "sources",
    [
        ["a" + BS + '"b, plain'],
        ["leading" + BS + "backslash", "plain"],
        ["values, with, many, commas", "plain"],
    ],
)
def test_following_item_is_not_swallowed(sources: list[str]) -> None:
    assert composed_sources(sources) == sources
    assert compose(composed_sources(sources)).count("sources: ") == 1


def test_composed_notes_carry_the_json_marker() -> None:
    assert MARKER in compose([COMMA_SOURCE])


def test_json_marker_present_even_for_empty_sources() -> None:
    assert MARKER in compose([])


@pytest.mark.parametrize(
    "sources",
    [
        [r"a\"b, plain"],
        [r"leading\backslash", "plain"],
        ["values, with, many, commas", "plain"],
    ],
)
def test_quoted_forms_round_trip(sources: list[str]) -> None:
    assert composed_sources(sources) == sources


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            '["notes/a, b", "c' + BS + BS + 'd", "quote ' + BS + QUOTE + ' inside"]',
            ["notes/a, b", "c" + BS + "d", 'quote " inside'],
        ),
        (
            '["tab' + BS + 'tvalue", "unicode ' + EACUTE + '"]',
            ["tab\tvalue", "unicode " + EACUTE],
        ),
        ('["plain", "second"]', ["plain", "second"]),
        ("[]", []),
    ],
)
def test_marked_json_sources_decode_independently(
    raw: str, expected: list[str]
) -> None:
    text = "---\n" + MARKER + "\nsources: " + raw + "\n---\n"
    assert parse(text)[0]["sources"] == expected


def test_marked_json_leading_backslashes_are_not_doubled() -> None:
    encoded = json.dumps([UNC_ROOT, "C:" + BS + "folder" + BS * 2])
    text = "---\n" + MARKER + "\nsources: " + encoded + "\n---\n"
    assert parse(text)[0]["sources"] == [UNC_ROOT, "C:" + BS + "folder" + BS * 2]


def test_memory_io_keeps_comma_source_through_the_lifecycle(tmp_path: Path) -> None:
    io = MemoryIO({"vault_path": str(tmp_path)})
    io.write_note("Round trip note", "first body", source=COMMA_SOURCE)
    path = io._find_note("Round trip note")
    assert path is not None
    assert parse(path.read_text(encoding="utf-8"))[0]["sources"] == [COMMA_SOURCE]
    io.write_note("Round trip note", "second body", append=True)
    assert parse(path.read_text(encoding="utf-8"))[0]["sources"] == [COMMA_SOURCE]
    io.write_note("Round trip note", "third body", source=COMMA_SOURCE, append=True)
    assert parse(path.read_text(encoding="utf-8"))[0]["sources"] == [COMMA_SOURCE]
    io.write_note(
        "Round trip note",
        "fourth body",
        source="notes/2026-01-03, evening",
        append=True,
    )
    meta, body = parse(path.read_text(encoding="utf-8"))
    assert meta["sources"] == [COMMA_SOURCE, "notes/2026-01-03, evening"]
    assert meta["version"] == 4
    assert body.strip().splitlines() == [
        "first body",
        "",
        "second body",
        "",
        "third body",
        "",
        "fourth body",
    ]


def test_memory_io_keeps_quote_backslash_source_through_the_lifecycle(
    tmp_path: Path,
) -> None:
    io = MemoryIO({"vault_path": str(tmp_path)})
    io.write_note("Mixed note", "first body", source=MIXED_SOURCE)
    path = io._find_note("Mixed note")
    assert path is not None
    assert parse(path.read_text(encoding="utf-8"))[0]["sources"] == [MIXED_SOURCE]
    io.write_note("Mixed note", "second body", append=True)
    assert parse(path.read_text(encoding="utf-8"))[0]["sources"] == [MIXED_SOURCE]
    io.write_note("Mixed note", "third body", source=MIXED_SOURCE, append=True)
    assert parse(path.read_text(encoding="utf-8"))[0]["sources"] == [MIXED_SOURCE]
    io.write_note("Mixed note", "fourth body", source="plain, source", append=True)
    meta, body = parse(path.read_text(encoding="utf-8"))
    assert meta["sources"] == [MIXED_SOURCE, "plain, source"]
    assert meta["version"] == 4
    assert body.strip().splitlines() == [
        "first body",
        "",
        "second body",
        "",
        "third body",
        "",
        "fourth body",
    ]


def test_memory_io_preserves_legacy_unmarked_comma_source(tmp_path: Path) -> None:
    legacy = compose([COMMA_SOURCE]).replace(MARKER + "\n", "")
    assert MARKER not in legacy
    note = tmp_path / "round-trip.md"
    note.write_text(legacy + "first body\n", encoding="utf-8")
    io = MemoryIO({"vault_path": str(tmp_path)})
    assert parse(note.read_text(encoding="utf-8"))[0]["sources"] == [COMMA_SOURCE]
    io.write_note("Round trip", "second body", append=True)
    meta, body = parse(note.read_text(encoding="utf-8"))
    assert meta["sources"] == [COMMA_SOURCE]
    assert meta["version"] == 2
    assert body.strip().splitlines() == ["first body", "", "second body"]


# --------------------------------------------------------------------------
# Compatibility guards: these pass on the unchanged base and must keep passing.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("['C:" + BS + "', 'plain']", [DRIVE_ROOT, "plain"]),
        (
            "['C:" + BS + "Users" + BS + "me" + BS + "notes', 'plain']",
            ["C:" + BS + "Users" + BS + "me" + BS + "notes", "plain"],
        ),
        ("['" + UNC_ROOT + "', 'plain']", [UNC_ROOT, "plain"]),
        ("['C:" + BS + "folder" + BS * 2 + "']", ["C:" + BS + "folder" + BS * 2]),
        ('["C:' + BS + '", "plain"]', [DRIVE_ROOT, "plain"]),
        ('["' + UNC_ROOT + '", "plain"]', [UNC_ROOT, "plain"]),
        ('["a' + BS * 4 + 'b", "plain"]', ["a" + BS * 4 + "b", "plain"]),
        (
            '["C:' + BS + "folder" + BS * 2 + '", "plain"]',
            ["C:" + BS + "folder" + BS * 2, "plain"],
        ),
    ],
)
def test_legacy_drive_root_lists_are_unchanged(raw: str, expected: list[str]) -> None:
    assert parsed_value(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("'C:" + BS + "'", DRIVE_ROOT),
        ("'" + UNC_ROOT + "'", UNC_ROOT),
        ("'C:" + BS + "folder" + BS * 2 + "'", "C:" + BS + "folder" + BS * 2),
        ('"C:' + BS + '"', DRIVE_ROOT),
        ('"' + UNC_ROOT + '"', UNC_ROOT),
        ('"C:' + BS + "folder" + BS * 2 + '"', "C:" + BS + "folder" + BS * 2),
        ('"a' + BS + QUOTE + 'b"', "a" + BS + QUOTE + "b"),
    ],
)
def test_legacy_quoted_scalars_are_unchanged(raw: str, expected: str) -> None:
    assert parsed_value(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("[someone's notes, plain]", ["someone's notes", "plain"]),
        (
            "[read " + QUOTE + "quoted" + QUOTE + " notes, plain]",
            ["read " + QUOTE + "quoted" + QUOTE + " notes", "plain"],
        ),
        ("['it''s fine']", ["it''s fine"]),
        (
            '["it' + APOS * 2 + 's fine", "plain"]',
            ["it" + APOS * 2 + "s fine", "plain"],
        ),
        ("['a" + BS + "nb', 'plain']", ["a" + BS + "nb", "plain"]),
        ("['a" + BS + "tb', 'plain']", ["a" + BS + "tb", "plain"]),
        ("['a" + BS + "qb', 'plain']", ["a" + BS + "qb", "plain"]),
        ("['" + BS + "u0041b', 'plain']", [BS + "u0041b", "plain"]),
        ("[a, b, c]", ["a", "b", "c"]),
        ("[[a, b], c]", [["a", "b"], "c"]),
        ("[]", []),
        ("[true, false, null]", [True, False, None]),
        ("[3, 1.5, -2]", [3, 1.5, -2]),
        ("['']", [""]),
        ("['  spaced  ', '" + chr(9) + "tabbed']", ["  spaced  ", "\ttabbed"]),
        ("['caf" + EACUTE + "']", ["caf" + EACUTE]),
        ('["C:' + BS + '", "plain", "other"]', [DRIVE_ROOT, "plain", "other"]),
        ("['C:" + BS + "', 'plain', 'other']", [DRIVE_ROOT, "plain", "other"]),
    ],
)
def test_inline_list_parsing_is_unchanged(raw: str, expected: object) -> None:
    assert parsed_value(raw) == expected


def test_parse_without_frontmatter_returns_body_unchanged() -> None:
    meta, body = parse("just a body\nwith lines\n")
    assert meta == {}
    assert body == "just a body\nwith lines\n"


def test_body_boundary_is_unchanged() -> None:
    meta, body = parse(compose([]) + "body text\n")
    assert meta["title"] == "Round trip"
    assert body.strip() == "body text"


def test_malformed_inline_lists_do_not_raise() -> None:
    for raw in ["[a, ", "['unterminated", '["a, b' + BS, "[[a, b]", "}", "]", "['a']]"]:
        parsed_value(raw)


# --------------------------------------------------------------------------
# New format boundary: the json-v1 marker contract.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "---\n" + MARKER + '\nsources: ["a, b"]\n---\n',
        '---\nsources: ["a, b"]\n' + MARKER + "\n---\n",
        "---\nsources_encoding: 'json-v1'\nsources: [\"a, b\"]\n---\n",
        '---\nsources_encoding:   json-v1  \nsources: ["a, b"]\n---\n',
        "---\nsources_encoding: old\n" + MARKER + '\nsources: ["a, b"]\n---\n',
    ],
)
def test_marker_position_and_quoting_do_not_matter(text: str) -> None:
    assert parse(text)[0]["sources"] == ["a, b"]


@pytest.mark.parametrize(
    "text, expected",
    [
        ('---\nsources_encoding: v2\nsources: ["a, b"]\n---\n', ["a, b"]),
        ('---\nsources: ["a, b"]\n---\n', ["a, b"]),
        (
            '---\nnested:\n  sources_encoding: json-v1\nsources: ["a, b"]\n---\n',
            ["a, b"],
        ),
        (
            '---\nnested:\n  sources_encoding: json-v1\n  sources: ["a, b"]\n---\n',
            {"nested": {"sources_encoding": "json-v1", "sources": ["a, b"]}},
        ),
    ],
)
def test_absent_unknown_and_indented_markers_keep_legacy_parsing(
    text: str, expected: object
) -> None:
    meta = parse(text)[0]
    if isinstance(expected, dict):
        assert meta == expected
    else:
        assert meta["sources"] == expected


def test_top_level_marker_does_not_affect_unrelated_quoted_fields() -> None:
    text = "---\n" + MARKER + '\ntitle: "quoted, title"\nsources: ["a, b"]\n---\n'
    meta = parse(text)[0]
    assert meta["title"] == "quoted, title"
    assert meta["sources"] == ["a, b"]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("---\nsources_encoding: json-v1\nsources: [oops\n---\n", "[oops"),
        ('---\nsources_encoding: json-v1\nsources: {"a": 1}\n---\n', '{"a": 1}'),
        ('---\nsources_encoding: json-v1\nsources: "not a list"\n---\n', "not a list"),
        ("---\nsources_encoding: json-v1\nsources: ['a', 'b']\n---\n", ["a", "b"]),
        ("---\nsources_encoding: json-v1\nsources: [1, 2]\n---\n", [1, 2]),
        ('---\nsources_encoding: json-v1\nsources: ["a", 2]\n---\n', ["a", 2]),
        ('---\nsources_encoding: json-v1\nsources: [["a"]]\n---\n', [["a"]]),
        ("---\nsources_encoding: json-v1\nsources: [not json\n---\n", "[not json"),
    ],
)
def test_invalid_marked_sources_degrade_without_raising(
    text: str, expected: object
) -> None:
    meta = parse(text)[0]
    assert meta["sources"] == expected
    assert meta["sources_encoding"] == "json-v1"


def test_marker_survives_a_rewrite_through_memory_io(tmp_path: Path) -> None:
    io = MemoryIO({"vault_path": str(tmp_path)})
    io.write_note("Marked note", "body", source=COMMA_SOURCE)
    path = io._find_note("Marked note")
    assert path is not None
    assert MARKER in path.read_text(encoding="utf-8")
    io.write_note("Marked note", "more", append=True)
    assert MARKER in path.read_text(encoding="utf-8")
    assert parse(path.read_text(encoding="utf-8"))[0]["sources"] == [COMMA_SOURCE]


def test_memory_io_converts_legacy_unmarked_windows_sources(tmp_path: Path) -> None:
    legacy = (
        "---\ntitle: Round trip\ntype: topic\ncreated: 2026-01-02\n"
        "updated: 2026-01-02\nconfidence: 0.7\npolarity: positive\nversion: 1\n"
        'sources: ["' + UNC_ROOT + '", "C:' + BS + "folder" + BS * 2 + '"]\n'
        "tags: []\n---\n\nbody\n"
    )
    assert MARKER not in legacy
    note = tmp_path / "round-trip.md"
    note.write_text(legacy, encoding="utf-8")
    expected = [UNC_ROOT, "C:" + BS + "folder" + BS * 2]
    assert parse(legacy)[0]["sources"] == expected
    io = MemoryIO({"vault_path": str(tmp_path)})
    io.write_note("Round trip", "second body", append=True)
    converted, _body = parse(note.read_text(encoding="utf-8"))
    assert converted["sources"] == expected
    assert MARKER in note.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "value",
    [
        "caf" + EACUTE + ", na" + IDIAERESIS + "ve",
        "line" + chr(0x2028) + "separator",
        "para" + chr(0x2029) + "separator",
        "line\nseparator",
        'quote " and ' + BS + " back",
    ],
)
def test_new_encoding_keeps_sources_on_one_physical_line(value: str) -> None:
    text = compose([value])
    front = text.split("---\n")[1]
    source_lines = [line for line in front.splitlines() if line.startswith("sources:")]
    assert len(source_lines) == 1
    assert parse(text)[0]["sources"] == [value]
