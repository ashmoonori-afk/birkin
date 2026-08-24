from birkin.skills import frontmatter

HERMES_SAMPLE = '''---
name: apple-notes
description: "Manage Apple Notes via memo CLI: create, search, edit."
version: 1.0.0
platforms: [macos]
metadata:
  hermes:
    tags: [Notes, Apple, macOS]
---

# Apple Notes
body here
'''


def test_parse_name_and_description():
    meta, body = frontmatter.parse(HERMES_SAMPLE)
    assert meta["name"] == "apple-notes"
    assert meta["description"].startswith("Manage Apple Notes")
    assert "# Apple Notes" in body


def test_nested_metadata_hermes_tags():
    meta, _ = frontmatter.parse(HERMES_SAMPLE)
    assert meta["metadata"]["hermes"]["tags"] == ["Notes", "Apple", "macOS"]


def test_quoted_description_with_colon_preserved():
    meta, _ = frontmatter.parse(HERMES_SAMPLE)
    # the colon inside the quoted description must survive
    assert "memo CLI: create" in meta["description"]


def test_inline_list_platforms():
    meta, _ = frontmatter.parse(HERMES_SAMPLE)
    assert meta["platforms"] == ["macos"]


def test_no_frontmatter_returns_empty_meta():
    meta, body = frontmatter.parse("just text, no frontmatter")
    assert meta == {}
    assert body == "just text, no frontmatter"


def test_split_frontmatter():
    fm, body = frontmatter.split_frontmatter(HERMES_SAMPLE)
    assert "name: apple-notes" in fm
    assert body.strip().startswith("# Apple Notes")


def test_extract_meta_regex_fallback():
    # description present even if the structured parse were to miss it
    meta, _ = frontmatter.extract_meta(HERMES_SAMPLE)
    assert meta.get("name") == "apple-notes"
    assert meta.get("description")


def test_malformed_list_then_mapping_degrades_without_raising():
    text = "---\nitems:\n  - first\n  broken: value\n---\n"

    meta, _ = frontmatter.parse(text)

    assert meta["items"] == ["first"]


def test_malformed_mapping_then_list_degrades_without_raising():
    text = "---\nitems:\n  first: value\n  - broken\n---\n"

    meta, _ = frontmatter.parse(text)

    assert meta["items"] == {"first": "value"}
