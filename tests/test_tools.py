"""Direct tests for the tool implementations (files, shell, web, subagent_tool)."""

from __future__ import annotations

import urllib.request
from pathlib import Path

import pytest

from birkin.tools import ToolContext, ToolResult, build_registry
from birkin.tools import files as files_mod
from birkin.tools import shell as shell_mod
from birkin.tools import subagent_tool as st_mod
from birkin.tools import web as web_mod


def _ctx(cwd: Path) -> ToolContext:
    return ToolContext(cfg={}, client=None, cwd=cwd, skills=None, memory=None)


# ---------------- files ----------------

def test_files_read_write_list_roundtrip(tmp_path: Path):
    ctx = _ctx(tmp_path)
    write = next(t for t in files_mod.tools() if t.name == "write_file").fn
    read = next(t for t in files_mod.tools() if t.name == "read_file").fn
    listt = next(t for t in files_mod.tools() if t.name == "list_files").fn

    res = write({"path": "a.txt", "content": "hello"}, ctx)
    assert not res.is_error and "Wrote" in res.content
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello"

    res = read({"path": "a.txt"}, ctx)
    assert "hello" in res.content

    # list_files at the workspace root sees a.txt
    res = listt({"path": "."}, ctx)
    assert "a.txt" in res.content

    # nested write creates parent dirs
    res = write({"path": "sub/dir/b.txt", "content": "x"}, ctx)
    assert (tmp_path / "sub" / "dir" / "b.txt").is_file()


def test_files_read_missing(tmp_path: Path):
    ctx = _ctx(tmp_path)
    read = next(t for t in files_mod.tools() if t.name == "read_file").fn
    res = read({"path": "nope.txt"}, ctx)
    assert res.is_error and "No such file" in res.content


def test_files_list_missing(tmp_path: Path):
    ctx = _ctx(tmp_path)
    listt = next(t for t in files_mod.tools() if t.name == "list_files").fn
    res = listt({"path": "ghost"}, ctx)
    assert res.is_error


def test_files_read_truncates_large(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(files_mod, "MAX_READ_BYTES", 10)
    p = tmp_path / "big.txt"
    p.write_text("0123456789ABCDEFGHIJ", encoding="utf-8")
    ctx = _ctx(tmp_path)
    read = next(t for t in files_mod.tools() if t.name == "read_file").fn
    res = read({"path": "big.txt"}, ctx)
    assert "truncated" in res.content


# ---------------- shell (run via argv shell, no shell=True) ----------------

def test_shell_runs_echo_and_returns_exit(tmp_path: Path):
    ctx = _ctx(tmp_path)
    fn = next(t for t in shell_mod.tools() if t.name == "run_shell").fn
    res = fn({"command": "echo birkin-shell-ok"}, ctx)
    assert not res.is_error
    assert "birkin-shell-ok" in res.content
    assert "[exit 0]" in res.content


def test_shell_empty_command_errors(tmp_path: Path):
    ctx = _ctx(tmp_path)
    fn = next(t for t in shell_mod.tools() if t.name == "run_shell").fn
    res = fn({"command": "   "}, ctx)
    assert res.is_error and "Empty" in res.content


# ---------------- web (monkeypatch urlopen — no network) ----------------

class _FakeResp:
    def __init__(self, body: bytes, ctype: str = "text/html"):
        self._body = body
        self.headers = {"Content-Type": ctype}

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, n=None): return self._body if n is None else self._body[:n]


def test_web_fetch_returns_text_stripped_of_html(monkeypatch, tmp_path):
    html = b"<html><head><style>x{}</style></head><body><h1>Hello</h1>" \
           b"<script>bad</script><p>World</p></body></html>"
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=30: _FakeResp(html, "text/html; charset=utf-8"))
    ctx = _ctx(tmp_path)
    fn = next(t for t in web_mod.tools() if t.name == "web_fetch").fn
    res = fn({"url": "https://example.test/"}, ctx)
    assert not res.is_error
    assert "Hello" in res.content and "World" in res.content
    assert "bad" not in res.content  # script content dropped


def test_web_fetch_missing_url(tmp_path):
    ctx = _ctx(tmp_path)
    fn = next(t for t in web_mod.tools() if t.name == "web_fetch").fn
    res = fn({"url": ""}, ctx)
    assert res.is_error


def test_web_fetch_network_error(monkeypatch, tmp_path):
    def boom(req, timeout=30):
        raise urllib.error.URLError("nope")  # type: ignore[name-defined]
    import urllib.error  # noqa
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    ctx = _ctx(tmp_path)
    fn = next(t for t in web_mod.tools() if t.name == "web_fetch").fn
    res = fn({"url": "https://example.test/"}, ctx)
    assert res.is_error and "Fetch failed" in res.content


# ---------------- subagent_tool (monkeypatch run_subagent) ----------------

def test_subagent_tool_delegates(monkeypatch, tmp_path):
    from birkin import subagent as subagent_mod
    monkeypatch.setattr(subagent_mod, "run_subagent",
                        lambda task, ctx, skill_names=None, max_turns=12: f"sub-reply:{task[:20]}")
    ctx = _ctx(tmp_path)
    fn = next(t for t in st_mod.subagent_tools() if t.name == "spawn_subagent").fn
    res = fn({"task": "investigate xyz"}, ctx)
    assert not res.is_error and res.content.startswith("sub-reply:")


def test_subagent_tool_missing_task(tmp_path):
    ctx = _ctx(tmp_path)
    fn = next(t for t in st_mod.subagent_tools() if t.name == "spawn_subagent").fn
    res = fn({"task": ""}, ctx)
    assert res.is_error


def test_subagent_tool_depth_limit(tmp_path):
    ctx = ToolContext(cfg={}, client=None, cwd=tmp_path, skills=None, memory=None,
                      depth=5, max_depth=2)
    fn = next(t for t in st_mod.subagent_tools() if t.name == "spawn_subagent").fn
    res = fn({"task": "x"}, ctx)
    assert res.is_error and "depth" in res.content.lower()


# ---------------- registry includes/excludes ----------------

def test_build_registry_include_groups(tmp_path):
    ctx = _ctx(tmp_path)
    names = build_registry(ctx, include={"files", "web"}).names()
    assert "read_file" in names and "web_fetch" in names
    assert "run_shell" not in names  # excluded


def test_build_registry_unknown_tool_returns_error(tmp_path):
    ctx = _ctx(tmp_path)
    reg = build_registry(ctx)
    res = reg.execute("nope_tool", {})
    assert res.is_error and "Unknown tool" in res.content


def test_build_registry_disabled_tools_filtered(tmp_path):
    ctx = ToolContext(cfg={"disabled_tools": ["run_shell"]}, client=None,
                      cwd=tmp_path, skills=None, memory=None)
    names = build_registry(ctx).names()
    assert "run_shell" not in names
    assert "read_file" in names
