"""Direct tests for the tool implementations (files, shell, web, subagent_tool)."""

from __future__ import annotations

import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import cast

import pytest

from birkin.tools import ToolContext, build_registry
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


@pytest.mark.parametrize(
    "network_path",
    [
        "//attacker.example/share/leak.txt",
        r"\\attacker.example\share\leak.txt",
        r"\\?\UNC\attacker.example\share\leak.txt",
        r"\\.\pipe\birkin-leak",
    ],
)
def test_enforced_egress_rejects_network_file_write_before_filesystem(
    tmp_path: Path,
    monkeypatch,
    network_path: str,
) -> None:
    ctx = ToolContext(
        cfg={"egress": {"enabled": True, "enforced": True}},
        client=None,
        cwd=tmp_path,
        skills=None,
        memory=None,
    )
    registry = build_registry(ctx)
    calls: list[tuple[str, str]] = []

    def write_target(path: Path, content: str) -> None:
        calls.append(("write", f"{path}:{content}"))

    monkeypatch.setattr(files_mod, "_atomic_write_text", write_target)

    result = registry.execute(
        "write_file",
        {"path": network_path, "content": "sensitive payload"},
    )

    assert result.is_error
    assert calls == []


@pytest.mark.parametrize(
    "network_path",
    [
        "Z:/share/leak.txt",
        r"Y:\sensitive.txt",
    ],
    ids=["forward-slash", "backslash"],
)
def test_enforced_egress_rejects_mapped_drive_before_filesystem(
    tmp_path: Path,
    monkeypatch,
    network_path: str,
) -> None:
    ctx = ToolContext(
        cfg={"egress": {"enabled": True, "enforced": True}},
        client=None,
        cwd=tmp_path,
        skills=None,
        memory=None,
    )
    registry = build_registry(ctx)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        files_mod,
        "_windows_drive_type",
        lambda _root: 4,
        raising=False,
    )
    monkeypatch.setattr(
        files_mod,
        "_atomic_write_text",
        lambda path, content: calls.append(("write", f"{path}:{content}")),
    )

    result = registry.execute(
        "write_file",
        {"path": network_path, "content": "sensitive payload"},
    )

    assert result.is_error
    assert calls == []


@pytest.mark.parametrize(
    "network_path",
    [
        "relative-secret.txt",
        r"\root-relative-secret.txt",
    ],
    ids=["relative", "root-relative"],
)
def test_enforced_egress_rejects_relative_write_from_mapped_workspace(
    monkeypatch,
    network_path: str,
) -> None:
    ctx = ToolContext(
        cfg={"egress": {"enabled": True, "enforced": True}},
        client=None,
        cwd=Path(r"Z:\mapped-workspace"),
        skills=None,
        memory=None,
    )
    registry = build_registry(ctx)
    drive_checks: list[str] = []
    filesystem_calls: list[str] = []

    def drive_type(root: str) -> int:
        drive_checks.append(root)
        return 4

    monkeypatch.setattr(files_mod, "_windows_drive_type", drive_type)
    monkeypatch.setattr(
        files_mod,
        "_atomic_write_text",
        lambda *_args, **_kwargs: filesystem_calls.append("write"),
    )

    result = registry.execute(
        "write_file",
        {"path": network_path, "content": "sensitive payload"},
    )

    assert result.is_error
    assert drive_checks == ["Z:\\"]
    assert filesystem_calls == []


def test_enforced_egress_allows_local_windows_drive_type(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ctx = ToolContext(
        cfg={"egress": {"enabled": True, "enforced": True}},
        client=None,
        cwd=tmp_path,
        skills=None,
        memory=None,
    )
    monkeypatch.setattr(
        files_mod,
        "_windows_drive_type",
        lambda _root: 3,
        raising=False,
    )

    assert not files_mod._network_path_blocked(
        ctx,
        r"C:\local\file.txt",
    )


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


@pytest.mark.skipif(os.name != "nt", reason="Windows TEMP normalization")
def test_shell_replaces_unwritable_windows_temp_env(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    expected_temp = tempfile.gettempdir()
    protected_temp = str(
        Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32"
    )
    monkeypatch.setenv("TEMP", protected_temp)
    monkeypatch.setenv("TMP", protected_temp)
    captured: dict[str, object] = {}

    def fake_run(
            argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(shell_mod.subprocess, "run", fake_run)
    fn = next(t for t in shell_mod.tools() if t.name == "run_shell").fn

    result = fn({"command": "echo ok"}, _ctx(tmp_path))
    child_env = cast(dict[str, str], captured["env"])

    assert result.is_error is False
    assert child_env["TEMP"] == expected_temp
    assert child_env["TMP"] == expected_temp


# ---------------- web (monkeypatch the opener — no network) ----------------
# web_fetch opens via build_opener(_GuardedRedirectHandler) (SSRF guard), so
# tests patch build_opener + DNS resolution, not the plain urlopen.

class _FakeResp:
    def __init__(self, body: bytes, ctype: str = "text/html"):
        self._body = body
        self.headers = {"Content-Type": ctype}

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, n=None): return self._body if n is None else self._body[:n]


class _FakeOpener:
    def __init__(self, resp):
        self._resp = resp

    def open(self, req, timeout=30):
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp


def _hermetic_web(monkeypatch, resp):
    """No-network web_fetch: public DNS answer + canned opener response."""
    import socket
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, port, *a, **k: [
                            (2, 1, 6, "", ("93.184.216.34", 0))])
    monkeypatch.setattr(urllib.request, "build_opener",
                        lambda *handlers: _FakeOpener(resp))


def test_web_fetch_returns_text_stripped_of_html(monkeypatch, tmp_path):
    html = b"<html><head><style>x{}</style></head><body><h1>Hello</h1>" \
           b"<script>bad</script><p>World</p></body></html>"
    _hermetic_web(monkeypatch, _FakeResp(html, "text/html; charset=utf-8"))
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
    import urllib.error
    _hermetic_web(monkeypatch, urllib.error.URLError("nope"))
    ctx = _ctx(tmp_path)
    fn = next(t for t in web_mod.tools() if t.name == "web_fetch").fn
    res = fn({"url": "https://example.test/"}, ctx)
    assert res.is_error and "Fetch failed" in res.content


# ---------------- subagent_tool (monkeypatch run_subagent) ----------------

def test_subagent_tool_delegates(monkeypatch, tmp_path):
    from birkin import subagent as subagent_mod
    seen = {}

    def fake_run(task, ctx, skill_names=None, max_turns=12, detach=False,
                 reserve_tokens=0, reserve_usd=0.0):
        seen["detach"] = detach
        seen["reserve"] = (reserve_tokens, reserve_usd)
        return f"sub-reply:{task[:20]}"

    monkeypatch.setattr(subagent_mod, "run_subagent", fake_run)
    ctx = _ctx(tmp_path)
    fn = next(t for t in st_mod.subagent_tools() if t.name == "spawn_subagent").fn
    res = fn({
        "task": "investigate xyz",
        "reserve_tokens": 200,
        "reserve_usd": 0.25,
    }, ctx)
    assert not res.is_error and res.content.startswith("sub-reply:")
    assert seen["detach"] is False
    assert seen["reserve"] == (200, 0.25)

    assert not fn({"task": "investigate xyz", "detach": True}, ctx).is_error
    assert seen["detach"] is True


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
