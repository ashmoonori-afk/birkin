"""Real RuntimeWorkspaceAdapter -> Session.ask -> workbench path."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pytest

from birkin.llm import LLMClient, StreamCallback
from birkin import runtime
from birkin.workspace import WorkspaceEvent
from birkin.workspace import runtime_adapter as adapter_module
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter
from birkin.workspace.service import WorkspaceService


class FakeModel(LLMClient):
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
        if on_text is not None:
            on_text("workspace reply")
        return {
            "role": "assistant",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "workspace reply"}],
        }


def test_adapter_uses_real_session_ask_and_records_workbench(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    fake = FakeModel()
    monkeypatch.setattr(runtime, "build_client", lambda _cfg, _key: fake)
    session = runtime.build_session(
        {
            "provider": "anthropic",
            "model": "fake",
            "session_id": "workspace-e2e",
            "self_improve": False,
            "harness_enabled": False,
        }
    )
    monkeypatch.setattr(
        adapter_module,
        "build_session",
        lambda _cfg, **_kwargs: session,
    )
    emitted: list[str] = []

    def emit(kind: str, payload: dict[str, object]) -> WorkspaceEvent:
        emitted.append(kind)
        return WorkspaceEvent(
            protocol_version=1,
            session_id="workspace-e2e",
            cursor=len(emitted),
            event_id=f"event-{len(emitted)}",
            type=kind,
            timestamp="2026-08-16T00:00:00Z",
            actor_id="e2e",
            command_id="e2e-command",
            payload=payload,
        )

    adapter = RuntimeWorkspaceAdapter("workspace-e2e", emit)
    result = adapter.handlers()["chat.send"]({"text": "exercise production"})
    service = WorkspaceService(
        root=tmp_path / "workspace",
        session_id="workspace-e2e",
        handlers={},
    )
    snapshot = adapter.enrich_snapshot(service.snapshot())

    assert result == {"reply": "workspace reply"}
    assert fake.systems
    assert emitted[0] == "message.user"
    assert "message.assistant.completed" in emitted
    assert snapshot.session_id == "workspace-e2e"
