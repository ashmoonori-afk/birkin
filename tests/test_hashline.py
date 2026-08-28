"""Hash-anchored line editing (v2 #2): pure module + edit_file/read_file tool."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from birkin.tools import ToolContext
from birkin.tools import file_atomic_replace
from birkin.tools import file_target_windows
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


def test_edit_file_atomic_replace_failure_preserves_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "f.txt"
    target.write_text("one\ntwo", encoding="utf-8")

    def fail_replace(*args, **kwargs) -> None:
        del args, kwargs
        raise OSError(errno.EIO, "injected atomic replace failure")

    monkeypatch.setattr(
        file_target_windows if os.name == "nt" else file_atomic_replace,
        "replace_with_backup" if os.name == "nt" else "exchange_between",
        fail_replace,
    )

    with pytest.raises(OSError):
        _ = _tool("edit_file")(
            {
                "path": "f.txt",
                "edits": [
                    {
                        "line": 2,
                        "hash": hashline.line_hash("two"),
                        "new": "changed",
                    }
                ],
            },
            _ctx(tmp_path),
        )

    assert target.read_text(encoding="utf-8") == "one\ntwo"


@pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX atomic exchange injection",
)
def test_edit_file_preserves_concurrent_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "f.txt"
    saved = tmp_path / "saved-original.txt"
    target.write_text("one\ntwo", encoding="utf-8")
    exchange = file_atomic_replace.exchange_between
    raced = False

    def replace_before_exchange(
        directory: int,
        first_name: str,
        second_name: str,
    ) -> None:
        nonlocal raced
        if not raced:
            raced = True
            os.rename(
                second_name,
                saved.name,
                src_dir_fd=directory,
                dst_dir_fd=directory,
            )
            replacement = os.open(
                second_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory,
            )
            try:
                _ = os.write(replacement, b"concurrent")
            finally:
                os.close(replacement)
        exchange(directory, first_name, second_name)

    monkeypatch.setattr(
        file_atomic_replace,
        "exchange_between",
        replace_before_exchange,
    )

    with pytest.raises(OSError, match="changed during atomic edit"):
        _ = _tool("edit_file")(
            {
                "path": "f.txt",
                "edits": [
                    {
                        "line": 2,
                        "hash": hashline.line_hash("two"),
                        "new": "changed",
                    }
                ],
            },
            _ctx(tmp_path),
        )

    assert target.read_bytes() == b"concurrent"
    assert saved.read_text(encoding="utf-8") == "one\ntwo"


@pytest.mark.skipif(
    os.name != "nt",
    reason="Windows ReplaceFile backup injection",
)
def test_edit_file_windows_preserves_concurrent_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "f.txt"
    saved = tmp_path / "saved-original.txt"
    target.write_text("one\ntwo", encoding="utf-8")
    replace = file_target_windows.replace_with_backup
    open_existing = file_target_windows.open_existing_deletable
    raced = False
    backup_swapped = False

    def replace_after_swap(
        target_path: Path,
        replacement: Path,
        backup: Path,
    ) -> None:
        nonlocal raced
        if not raced:
            raced = True
            target_path.rename(saved)
            concurrent = file_target_windows.open_created(target_path)
            try:
                _ = os.write(concurrent, b"concurrent")
                os.fsync(concurrent)
                replace(target_path, replacement, backup)
            finally:
                os.close(concurrent)
            return
        replace(target_path, replacement, backup)

    def swap_backup_after_open(path: Path) -> int:
        nonlocal backup_swapped
        descriptor = open_existing(path)
        if "birkin-edit-backup" in path.name and not backup_swapped:
            backup_swapped = True
            attacker = open_existing(path)
            try:
                file_target_windows.move_open_descriptor_no_replace(
                    attacker,
                    tmp_path / "saved-concurrent.txt",
                )
            finally:
                os.close(attacker)
            decoy = file_target_windows.open_created(path)
            try:
                _ = os.write(decoy, b"attacker backup")
                os.fsync(decoy)
            finally:
                os.close(decoy)
        return descriptor

    monkeypatch.setattr(
        file_target_windows,
        "replace_with_backup",
        replace_after_swap,
    )
    monkeypatch.setattr(
        file_target_windows,
        "open_existing_deletable",
        swap_backup_after_open,
    )

    with pytest.raises(OSError, match="changed during atomic edit"):
        _ = _tool("edit_file")(
            {
                "path": "f.txt",
                "edits": [
                    {
                        "line": 2,
                        "hash": hashline.line_hash("two"),
                        "new": "changed",
                    }
                ],
            },
            _ctx(tmp_path),
        )

    assert raced is True
    assert backup_swapped is True
    assert target.read_bytes() == b"concurrent"
    assert saved.read_text(encoding="utf-8") == "one\ntwo"
    attacker = tuple(tmp_path.glob(".f.txt.birkin-edit-backup-*"))
    assert len(attacker) == 1
    assert attacker[0].read_bytes() == b"attacker backup"


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
