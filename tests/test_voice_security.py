from __future__ import annotations

import types

from birkin.gateway import core as gw_core


def test_voice_channel_never_receives_approved_work(
    monkeypatch,
) -> None:
    observed: list[tuple[bool, bool]] = []
    context = types.SimpleNamespace(
        subagent_approval_required=False,
        approved_work=False,
    )
    agent = types.SimpleNamespace(messages=[])

    def ask(text, **_kwargs):
        observed.append(
            (
                context.subagent_approval_required,
                context.approved_work,
            )
        )
        agent.messages.append(
            {"role": "user", "content": [{"type": "text", "text": text}]}
        )
        return "approval required"

    session = types.SimpleNamespace(
        cfg={},
        agent=agent,
        ask=ask,
        ctx=context,
    )
    monkeypatch.setattr(gw_core, "build_session", lambda _cfg: session)
    gateway = gw_core.Gateway({"gateway_persistent": False})

    reply = gateway.handle(
        "voice",
        "voice-fixed",
        "delete every project",
    )

    assert reply == "approval required"
    assert observed == [(False, False)]
    assert context.subagent_approval_required is False
    assert context.approved_work is False
