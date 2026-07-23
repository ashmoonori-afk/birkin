"""Oversized tool output is saved to disk rather than discarded."""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin.tools import Tool, ToolContext, ToolRegistry, ToolResult, spill


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    yield tmp_path


def _cfg(**kw):
    base = {"spill_threshold": 1000, "spill_dir": "", "spill_retention_days": 7}
    base.update(kw)
    return base


# -- the decision ----------------------------------------------------------

def test_small_output_passes_through_unchanged():
    text = "short"
    assert spill.maybe_spill(text, "run_shell", _cfg()) is text


def test_large_output_is_written_and_referenced():
    body = "\n".join(f"line {i}" for i in range(5000))
    out = spill.maybe_spill(body, "run_shell", _cfg())

    assert spill.MARKER in out
    assert str(len(body)) in out
    path = Path(out.split("saved at:\n")[1].splitlines()[0])
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == body, "full output preserved"
    assert len(out) < len(body)


def test_preview_shows_the_start_of_the_output():
    body = "FIRST LINE\n" + "x" * 50_000
    out = spill.maybe_spill(body, "run_shell", _cfg())
    assert "FIRST LINE" in out


def test_read_file_is_exempt_so_reads_cannot_loop():
    body = "y" * 50_000
    assert spill.maybe_spill(body, "read_file", _cfg()) is body


def test_threshold_zero_disables_spilling():
    body = "y" * 50_000
    assert spill.maybe_spill(body, "run_shell", _cfg(spill_threshold=0)) is body


def test_write_failure_falls_back_to_inline_truncation(monkeypatch):
    monkeypatch.setattr(Path, "write_text",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("full")))
    body = "z" * 50_000
    out = spill.maybe_spill(body, "run_shell", _cfg())
    assert out.endswith("[output truncated]")
    assert len(out) < len(body)


def test_retention_sweep_removes_old_spills(tmp_path, monkeypatch):
    import time
    directory = spill.spill_dir(_cfg())
    stale = directory / "old_run_shell_deadbeef.txt"
    stale.write_text("old", encoding="utf-8")
    import os
    old = time.time() - 30 * 86400
    os.utime(stale, (old, old))

    spill.maybe_spill("q" * 50_000, "run_shell", _cfg())
    assert not stale.exists()


# -- registry integration --------------------------------------------------

def _registry(content: str, cfg=None) -> ToolRegistry:
    ctx = ToolContext(cfg=cfg or _cfg(), client=None, cwd=Path("."))
    reg = ToolRegistry(ctx)
    reg.register(Tool(name="big", description="d", input_schema={},
                      fn=lambda inp, c: ToolResult(content)))
    return reg


def test_registry_spills_every_tool_result():
    body = "w" * 50_000
    res = _registry(body).execute("big", {})
    assert spill.MARKER in res.content
    assert not res.is_error


def test_registry_preserves_the_error_flag():
    ctx = ToolContext(cfg=_cfg(), client=None, cwd=Path("."))
    reg = ToolRegistry(ctx)
    reg.register(Tool(name="boom", description="d", input_schema={},
                      fn=lambda inp, c: ToolResult("e" * 50_000, is_error=True)))
    res = reg.execute("boom", {})
    assert spill.MARKER in res.content and res.is_error is True


def test_registry_leaves_small_results_alone():
    res = _registry("tiny").execute("big", {})
    assert res.content == "tiny"


# -- the recovery path -----------------------------------------------------

def _read(path, **kw):
    from birkin.tools import files
    ctx = ToolContext(cfg={}, client=None, cwd=Path(path).parent)
    return files._read_file({"path": str(path), **kw}, ctx)


def test_read_file_offset_pages_through_a_spill_file(tmp_path):
    from birkin.tools import files
    big = tmp_path / "big.txt"
    # newline="" so the bytes on disk match what we compare against — offsets
    # are byte offsets, and Windows would otherwise expand \n to \r\n.
    big.write_text("".join(f"{i:07d}\n" for i in range(60_000)),
                   encoding="utf-8", newline="")
    raw = big.read_bytes()

    first = _read(big)
    assert not first.is_error
    assert "continue with offset=" in first.content
    offset = int(first.content.rsplit("offset=", 1)[1].rstrip("]\n"))
    assert offset == files.MAX_READ_BYTES

    second = _read(big, offset=offset)
    # The windows join back up: no bytes lost, none repeated.
    assert raw[offset:offset + 40].decode() in second.content

    # Paging to the end reaches the final line the first read could not show.
    seen, cursor = "", 0
    while cursor is not None and cursor < len(raw):
        res = _read(big, offset=cursor)
        seen += res.content.split("\n\n[truncated")[0]
        cursor = (int(res.content.rsplit("offset=", 1)[1].rstrip("]\n"))
                  if "continue with offset=" in res.content else None)
    assert "0059999" in seen


def test_read_file_rejects_offset_past_eof(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("hello", encoding="utf-8")
    res = _read(p, offset=999)
    assert res.is_error and "past the end" in res.content


def test_read_file_rejects_annotate_with_offset(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("hello\nworld\n", encoding="utf-8")
    res = _read(p, offset=2, annotate=True)
    assert res.is_error and "cannot be combined" in res.content


def test_read_file_annotate_still_works_without_offset(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("hello\nworld\n", encoding="utf-8")
    res = _read(p, annotate=True)
    assert not res.is_error and res.content.startswith("1#")
