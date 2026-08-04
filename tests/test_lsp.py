"""A synchronous LSP client: real framing, a real server process, real deltas.

An edit tool that cannot tell the model whether the file still compiles makes
the agent discover its own syntax error two turns later, from a failing test.
Language servers answer that question, and they speak one wire format:
Content-Length framed JSON-RPC over stdio.

asyncio is out of bounds here by project decision, so this is threading plus
subprocess: one reader thread drains stdout, replies are matched by id, and
every wait is bounded. A language server that hangs must never hang birkin.

Nothing in this file is mocked. The framing tests run over real byte streams,
and the client tests drive a real child process that speaks real LSP -- a
Python script standing in for a language server, so the contract is proven even
on a machine with no language server installed.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from birkin.lsp import protocol
from birkin.lsp.client import LspClient, LspError

# A server that speaks the protocol correctly, and can be told to misbehave.
FAKE_SERVER = r"""
import json, sys, time

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

MODE = sys.argv[1] if len(sys.argv) > 1 else "good"

while True:
    msg = read()
    if msg is None:
        break
    method, mid = msg.get("method"), msg.get("id")
    if MODE == "die":
        sys.exit(3)
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid,
              "result": {"capabilities": {"textDocumentSync": 1}}})
    elif method == "textDocument/didOpen":
        uri = msg["params"]["textDocument"]["uri"]
        send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
              "params": {"uri": uri, "diagnostics": [
                  {"range": {"start": {"line": 2, "character": 4},
                             "end": {"line": 2, "character": 9}},
                   "severity": 1, "code": "E999",
                   "message": "정의되지 않은 이름 'foo'"},
                  {"range": {"start": {"line": 7, "character": 0},
                             "end": {"line": 7, "character": 3}},
                   "severity": 2, "code": "W1", "message": "unused import"}]}})
    elif method == "silent":
        pass                                    # never answers, on purpose
    elif method == "shutdown":
        send({"jsonrpc": "2.0", "id": mid, "result": None})
    elif method == "exit":
        break
    elif mid is not None:
        send({"jsonrpc": "2.0", "id": mid, "result": {"echo": method}})
"""


@pytest.fixture()
def server_script(tmp_path) -> Path:
    path = tmp_path / "fake_lsp_server.py"
    path.write_text(FAKE_SERVER, encoding="utf-8")
    return path


def _argv(script: Path, mode: str = "good") -> list[str]:
    return [sys.executable, str(script), mode]


class TestFraming:
    def test_encode_writes_a_content_length_header(self) -> None:
        raw = protocol.encode({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        head, _, body = raw.partition(b"\r\n\r\n")
        assert head.startswith(b"Content-Length: ")
        assert int(head.split(b":")[1].strip()) == len(body)

    def test_length_counts_bytes_not_characters(self) -> None:
        """CJK is multi-byte. A character count desynchronises the whole stream."""
        raw = protocol.encode({"message": "정의되지 않은 이름"})
        head, _, body = raw.partition(b"\r\n\r\n")
        declared = int(head.split(b":")[1].strip())
        assert declared == len(body)
        assert declared > len("정의되지 않은 이름")

    def test_read_returns_the_decoded_message(self) -> None:
        stream = io.BytesIO(protocol.encode({"id": 7, "result": "ok"}))
        assert protocol.read_message(stream) == {"id": 7, "result": "ok"}

    def test_two_messages_in_one_stream_are_read_in_order(self) -> None:
        stream = io.BytesIO(protocol.encode({"id": 1}) + protocol.encode({"id": 2}))
        assert protocol.read_message(stream)["id"] == 1
        assert protocol.read_message(stream)["id"] == 2
        assert protocol.read_message(stream) is None

    def test_unknown_headers_are_tolerated(self) -> None:
        body = b'{"id":3}'
        stream = io.BytesIO(
            b"Content-Type: application/vscode-jsonrpc; charset=utf-8\r\n"
            b"Content-Length: %d\r\n\r\n%s" % (len(body), body))
        assert protocol.read_message(stream)["id"] == 3

    def test_a_closed_stream_reads_as_nothing(self) -> None:
        assert protocol.read_message(io.BytesIO(b"")) is None

    def test_a_header_without_a_length_is_refused(self) -> None:
        with pytest.raises(LspError):
            protocol.read_message(io.BytesIO(b"Content-Type: x\r\n\r\n{}"))

    def test_a_truncated_body_is_refused_not_silently_short(self) -> None:
        with pytest.raises(LspError):
            protocol.read_message(io.BytesIO(b"Content-Length: 50\r\n\r\n{}"))


class TestClientAgainstARealServer:
    def test_initialize_returns_the_servers_capabilities(self, server_script) -> None:
        with LspClient(_argv(server_script)) as client:
            result = client.request("initialize", {"processId": None})
            assert result["capabilities"]["textDocumentSync"] == 1

    def test_published_diagnostics_are_collected(self, server_script, tmp_path) -> None:
        source = tmp_path / "example.py"
        source.write_text("x = 1\n", encoding="utf-8")
        with LspClient(_argv(server_script)) as client:
            client.request("initialize", {"processId": None})
            found = client.diagnostics_for(source, "x = 1\n")
        assert [d["code"] for d in found] == ["E999", "W1"]
        assert "정의되지 않은" in found[0]["message"]

    def test_a_server_that_never_answers_times_out_instead_of_hanging(
            self, server_script) -> None:
        with LspClient(_argv(server_script), timeout=0.5) as client:
            with pytest.raises(LspError):
                client.request("silent", {})

    def test_a_server_that_dies_reports_rather_than_blocking(
            self, server_script) -> None:
        with LspClient(_argv(server_script, "die"), timeout=2.0) as client:
            with pytest.raises(LspError):
                client.request("initialize", {"processId": None})

    def test_a_missing_binary_is_a_clean_refusal(self) -> None:
        with pytest.raises(LspError):
            LspClient(["definitely-not-installed-language-server-xyz"])

    def test_close_leaves_no_child_process_running(self, server_script) -> None:
        client = LspClient(_argv(server_script))
        client.request("initialize", {"processId": None})
        client.close()
        assert client.returncode is not None


class TestDeltaBaseline:
    D_ONE = {"range": {"start": {"line": 2, "character": 4}},
             "severity": 1, "code": "E999", "message": "undefined name"}
    D_TWO = {"range": {"start": {"line": 7, "character": 0}},
             "severity": 2, "code": "W1", "message": "unused import"}

    def test_without_a_baseline_everything_is_new(self) -> None:
        assert protocol.new_since([], [self.D_ONE, self.D_TWO]) == \
            [self.D_ONE, self.D_TWO]

    def test_a_diagnostic_already_in_the_baseline_is_not_reported_again(self) -> None:
        """A file with pre-existing warnings must not blame them on this edit."""
        assert protocol.new_since([self.D_ONE], [self.D_ONE, self.D_TWO]) == \
            [self.D_TWO]

    def test_a_clean_edit_reports_nothing(self) -> None:
        assert protocol.new_since([self.D_ONE], [self.D_ONE]) == []

    def test_the_same_message_on_a_different_line_is_new(self) -> None:
        moved = {**self.D_ONE,
                 "range": {"start": {"line": 40, "character": 4}}}
        assert protocol.new_since([self.D_ONE], [moved]) == [moved]

    def test_a_fixed_diagnostic_does_not_appear_as_new(self) -> None:
        assert protocol.new_since([self.D_ONE, self.D_TWO], [self.D_TWO]) == []


def test_the_package_uses_no_asyncio() -> None:
    """A project decision, and a machine-checkable one: threads and pipes only."""
    from birkin import lsp
    root = Path(lsp.__file__).parent
    offenders = [p.name for p in root.glob("*.py")
                 if "import asyncio" in p.read_text(encoding="utf-8")]
    assert offenders == []
