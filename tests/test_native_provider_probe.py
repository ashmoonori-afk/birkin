from __future__ import annotations

from scripts.native import provider_probe


class _Session:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.closed = False

    def ask(self, _prompt: str, **_kwargs: object) -> str:
        return self.reply

    def close(self) -> None:
        self.closed = True


def test_probe_accepts_only_exact_provider_marker(monkeypatch) -> None:
    session = _Session(provider_probe.MARKER)
    monkeypatch.setattr(provider_probe, "build_session", lambda _cfg: session)

    record, status = provider_probe.run_probe(
        provider="codex-cli", model="default"
    )

    assert status == 0
    assert record["status"] == "pass"
    assert record["reply_bytes"] == len(provider_probe.MARKER)
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
