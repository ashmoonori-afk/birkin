"""Hash-anchored line editing (v2 #2): pure module + edit_file/read_file tool."""

from __future__ import annotations

from pathlib import Path

from birkin.tools import ToolContext
from birkin.tools import files as files_mod
from birkin.tools import hashline


def _ctx(cwd: Path) -> ToolContext:
    return ToolContext(cfg={}, client=None, cwd=cwd, skills=None, memory=None)


def _tool(name: str):
    return next(t for t in files_mod.tools() if t.name == name).fn


# ---------------- pure module --------------------------------------------

def test_line_hash_deterministic_and_distinct():
    assert hashline.line_hash("abc") == hashline.line_hash("abc")
    assert hashline.line_hash("abc") != hashline.line_hash("abd")
    assert len(hashline.line_hash("anything")) == 4


def test_annotate_tags_lines():
    text = "first\nsecond\n  indented"
    ann = hashline.annotate(text)
    lines = ann.split("\n")
    assert lines[0].startswith("1#") and "| first" in lines[0]
    assert lines[1].startswith("2#") and "| second" in lines[1]


def test_edit_text_applies_valid_edit():
    text = "alpha\nbeta\ngamma"
    h = hashline.line_hash("beta")
    new, errs = hashline.edit_text(text, [{"line": 2, "hash": h, "new": "BETA"}])
    assert errs == [] and new == "alpha\nBETA\ngamma"


def test_edit_text_rejects_stale_hash_without_changing():
    text = "alpha\nbeta\ngamma"
    new, errs = hashline.edit_text(text, [{"line": 2, "hash": "0000", "new": "X"}])
    assert new == text                            # untouched
    assert errs and "stale" in errs[0]


def test_edit_text_out_of_range_rejected():
    text = "only-line"
    new, errs = hashline.edit_text(text, [{"line": 9, "hash": "abcd", "new": "X"}])
    assert new == text and errs and "out of range" in errs[0]


def test_edit_text_all_or_nothing():
    text = "a\nb\nc"
    edits = [
        {"line": 1, "hash": hashline.line_hash("a"), "new": "A"},   # valid
        {"line": 3, "hash": "dead", "new": "C"},                    # stale
    ]
    new, errs = hashline.edit_text(text, edits)
    assert new == text and errs              # the valid one is NOT applied either


def test_edit_text_multiline_replacement():
    text = "x\ny\nz"
    h = hashline.line_hash("y")
    new, errs = hashline.edit_text(text, [{"line": 2, "hash": h, "new": "y1\ny2"}])
    assert errs == [] and new == "x\ny1\ny2\nz"


# ---------------- tool integration ---------------------------------------

def test_read_file_annotate_then_edit_roundtrip(tmp_path: Path):
    ctx = _ctx(tmp_path)
    (tmp_path / "f.txt").write_bytes(b"one\ntwo\nthree")   # force LF on Windows
    read, edit = _tool("read_file"), _tool("edit_file")

    annotated = read({"path": "f.txt", "annotate": True}, ctx).content
    assert annotated.split("\n")[1].startswith("2#")   # "2#<hash>| two"
    hash_two = hashline.line_hash("two")

    res = edit({"path": "f.txt",
                "edits": [{"line": 2, "hash": hash_two, "new": "TWO"}]}, ctx)
    assert not res.is_error and "Applied 1 edit" in res.content
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "one\nTWO\nthree"
    assert not list(tmp_path.glob("*.tmp"))            # atomic write left no temp


def test_edit_file_rejects_stale_and_leaves_file_untouched(tmp_path: Path):
    ctx = _ctx(tmp_path)
    (tmp_path / "f.txt").write_bytes(b"keep\nme")
    edit = _tool("edit_file")
    res = edit({"path": "f.txt",
                "edits": [{"line": 1, "hash": "0000", "new": "WIPED"}]}, ctx)
    assert res.is_error and "rejected" in res.content.lower()
    assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "keep\nme"


def test_read_file_without_annotate_is_unchanged(tmp_path: Path):
    ctx = _ctx(tmp_path)
    (tmp_path / "f.txt").write_bytes(b"plain\ntext")
    out = _tool("read_file")({"path": "f.txt"}, ctx).content
    assert out == "plain\ntext"                        # no tags by default
