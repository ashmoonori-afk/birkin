from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from birkin.cli import build_parser
from birkin.native import provider_probe


def test_packaged_helper_exposes_provider_probe_command(tmp_path) -> None:
    output = tmp_path / "probe.json"

    args = build_parser().parse_args([
        "native-bridge", "provider-probe",
        "--provider", "codex-cli",
        "--model", "default",
        "--output", str(output),
    ])

    assert args.native_bridge_action == "provider-probe"
    assert args.provider == "codex-cli"
    assert args.model == "default"
    assert args.output == output


class _Session:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.closed = False
        self.client = SimpleNamespace(
            provider="codex-cli", model="default", transport="cli"
        )
        self.ctx = SimpleNamespace(cwd=Path.cwd())

    def ask(self, _prompt: str, **_kwargs: object) -> str:
        return self.reply

    def close(self) -> None:
        self.closed = True


def test_probe_accepts_only_exact_provider_marker(monkeypatch, tmp_path) -> None:
    session = _Session(provider_probe.MARKER)
    monkeypatch.setattr(provider_probe, "build_session", lambda _cfg: session)

    output = tmp_path / "provider-probe.json"
    record, status = provider_probe.run_probe(
        provider="codex-cli", model="default", artifact_path=output
    )

    assert status == 0
    assert record["status"] == "pass"
    assert record["reply_bytes"] == len(provider_probe.MARKER)
    assert record["route"] == "cli"
    assert record["cwd"] == str(Path.cwd())
    assert record["artifact_paths"] == {
        "browser_runtime": "not-frozen",
        "probe": str(output.resolve()),
        "runtime_executable": str(Path(sys.executable).resolve()),
    }
    assert record["home"] == str(Path.home().resolve())
    assert record["search_path"]
    assert "reply" not in record
    assert session.closed is True


def test_probe_rejects_canned_or_credential_error_text(monkeypatch) -> None:
    for reply in (
        "The native packaged app is connected to Python authority.",
        "401 Unauthorized: refresh_token_reused",
    ):
        session = _Session(reply)
        monkeypatch.setattr(provider_probe, "build_session", lambda _cfg: session)

        record, status = provider_probe.run_probe(
            provider="codex-cli", model="default"
        )

        assert status == 1
        assert record["status"] == "fail"
        assert "reply" not in record
        assert session.closed is True
