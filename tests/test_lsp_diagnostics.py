"""After an edit, say whether the file still compiles.

An edit tool that returns "ok" and nothing else makes the agent discover its
own syntax error two turns later, from an unrelated failing test. A language
server already knows, and birkin now has a synchronous client for one.

Off by default and free when off: no configured server for the suffix means no
subprocess, no import, and the tool result is byte-identical to before. That
matters because most edits are to files no server is configured for, and every
one of them would otherwise pay a process spawn.

Only NEW diagnostics are reported. A file that already had ten warnings must
not blame all ten on this edit.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from birkin.lsp import diagnostics as diag
from birkin.tools import ToolContext, build_registry
from birkin.tools import hashline

# A server that reports one problem on the first open and two on the second,
# so the delta rule has something real to filter.
FAKE_SERVER = r"""
import json, sys

state = {"opens": 0}

def read():
    length = None
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        name, _, value = line.decode("ascii", "replace").partition(":")
        if name.strip().lower() == "content-length":
            length = int(value.strip())
    if length is None:
        return None
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))

def send(payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(body))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()

def diagnostic(line, code, message):
    return {"range": {"start": {"line": line, "character": 0},
                      "end": {"line": line, "character": 3}},
            "severity": 1, "code": code, "message": message}

while True:
    msg = read()
    if msg is None:
        break
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {"capabilities": {}}})
    elif method == "textDocument/didOpen":
        state["opens"] += 1
        uri = msg["params"]["textDocument"]["uri"]
        found = [diagnostic(0, "W-OLD", "pre-existing warning")]
        if state["opens"] >= 2:
            found.append(diagnostic(5, "E-NEW", "정의되지 않은 이름 'foo'"))
        send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
              "params": {"uri": uri, "diagnostics": found}})
    elif method == "shutdown":
        send({"jsonrpc": "2.0", "id": mid, "result": None})
    elif method == "exit":
        break
"""


@pytest.fixture()
def server(tmp_path) -> Path:
    path = tmp_path / "fake_server.py"
    path.write_text(FAKE_SERVER, encoding="utf-8")
    return path


def _one_edit(old_line: str, new_line: str) -> list[dict]:
    """One hash-anchored edit for line 1.

    edit_file refuses an edit whose hash does not match the line the agent
    claims to have seen, so the test has to compute it the same way the tool
    does rather than inventing one.
    """
    return [{"line": 1, "hash": hashline.line_hash(old_line), "new": new_line}]


def _cfg(server: Path | None) -> dict:
    if server is None:
        return {"spill_threshold": 0}
    return {"spill_threshold": 0, "lsp_servers":
            {".py": [sys.executable, str(server)]}}


class TestOffByDefault:
    def test_no_configuration_means_no_diagnostics(self, tmp_path) -> None:
        assert diag.report_for(tmp_path / "x.py", "x = 1\n", {}) == ""

    def test_an_unconfigured_suffix_is_skipped(self, server, tmp_path) -> None:
        assert diag.report_for(tmp_path / "notes.txt", "hello",
                               _cfg(server)) == ""

    def test_an_edit_result_is_unchanged_when_unconfigured(self, tmp_path) -> None:
        target = tmp_path / "app.py"
        target.write_text("value = 1\n", encoding="utf-8")
        registry = build_registry(ToolContext(cfg=_cfg(None), client=None,
                                              cwd=tmp_path))
        result = registry.execute("edit_file", {
            "path": str(target), "edits": _one_edit("value = 1", "value = 2")})
        assert result.is_error is False
        assert "diagnostic" not in result.content.lower()


class TestOnlyNewProblemsAreReported:
    def test_the_new_diagnostic_is_reported(self, server, tmp_path) -> None:
        target = tmp_path / "app.py"
        target.write_text("value = 1\n", encoding="utf-8")
        report = diag.report_for(target, "value = 2\n", _cfg(server),
                                 baseline_text="value = 1\n")
        assert "E-NEW" in report
        assert "정의되지 않은" in report

    def test_a_pre_existing_warning_is_not_blamed_on_this_edit(
            self, server, tmp_path) -> None:
        target = tmp_path / "app.py"
        target.write_text("value = 1\n", encoding="utf-8")
        report = diag.report_for(target, "value = 2\n", _cfg(server),
                                 baseline_text="value = 1\n")
        assert "W-OLD" not in report


class TestFailureIsNeverFatal:
    def test_a_missing_server_binary_costs_the_edit_nothing(self, tmp_path) -> None:
        cfg = {"lsp_servers": {".py": ["definitely-not-installed-xyz"]}}
        assert diag.report_for(tmp_path / "x.py", "x = 1\n", cfg) == ""

    def test_a_malformed_server_entry_is_ignored(self, tmp_path) -> None:
        assert diag.report_for(tmp_path / "x.py", "x = 1\n",
                               {"lsp_servers": {".py": "not-a-list"}}) == ""


class TestWiredIntoTheEditPath:
    def test_edit_file_appends_the_report(self, server, tmp_path) -> None:
        target = tmp_path / "app.py"
        target.write_text("value = 1\n", encoding="utf-8")
        registry = build_registry(ToolContext(cfg=_cfg(server), client=None,
                                              cwd=tmp_path))
        result = registry.execute("edit_file", {
            "path": str(target), "edits": _one_edit("value = 1", "value = 2")})
        assert result.is_error is False
        assert "E-NEW" in result.content

    def test_a_failed_edit_reports_no_diagnostics(self, server, tmp_path) -> None:
        """A miss did not change the file, so there is nothing to diagnose."""
        target = tmp_path / "app.py"
        target.write_text("value = 1\n", encoding="utf-8")
        registry = build_registry(ToolContext(cfg=_cfg(server), client=None,
                                              cwd=tmp_path))
        result = registry.execute("edit_file", {
            "path": str(target),
            "edits": [{"line": 1, "hash": "000000", "new": "x"}]})
        assert result.is_error is True
        assert "E-NEW" not in result.content
