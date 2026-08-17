"""CLI Working Memory update -> same production gateway turn injection."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import pytest

from birkin import runtime
from birkin.gateway import core as gateway_core
from birkin.llm import LLMClient, StreamCallback


class FakeGatewayModel(LLMClient):
    def __init__(self) -> None:
        super().__init__(
            provider="anthropic",
            model="fake",
            api_key="",
            base_url="https://example.invalid",
        )
        self.systems: list[str] = []

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        model: Optional[str] = None,
        on_text: StreamCallback = None,
        abort: Optional[Any] = None,
    ) -> dict[str, Any]:
        self.systems.append(system)
        return {
            "role": "assistant",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "gateway-ok"}],
        }


def test_cli_update_is_fresh_in_same_gateway_conversation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    session_id = gateway_core.conversation_session_id("telegram", "42")
    env = os.environ.copy()
    env["BIRKIN_HOME"] = str(tmp_path)
    updated = subprocess.run(
        [
            sys.executable,
            "-m",
            "birkin",
            "working-memory",
            "update",
            "--session",
            session_id,
            "--correction",
            "Use the verified gateway path",
            "--next-action",
            "Reply through this turn",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert updated.returncode == 0, updated.stdout + updated.stderr

    fake = FakeGatewayModel()
    monkeypatch.setattr(runtime, "build_client", lambda _cfg, _key: fake)
    session = runtime.build_session(
        {
            "provider": "anthropic",
            "model": "fake",
            "session_id": session_id,
            "self_improve": False,
            "harness_enabled": True,
            "gateway_persistent": False,
        }
    )
    monkeypatch.setattr(gateway_core, "build_session", lambda _cfg: session)
    gateway = gateway_core.Gateway(dict(session.cfg))

    reply = gateway.handle("telegram", "42", "continue")

    assert reply == "gateway-ok"
    assert "Use the verified gateway path" in fake.systems[-1]
    assert "Reply through this turn" in fake.systems[-1]
