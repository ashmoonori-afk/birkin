from __future__ import annotations

import json


def test_dispatch_keeps_literal_help_behavior(capsys):
    from birkin import slashcommands

    class Session:
        pass

    assert slashcommands.dispatch(Session(), "/help") == "continue"
    assert "Slash commands" in capsys.readouterr().out


def test_dispatch_command_uses_same_help_handler(capsys):
    from birkin import slashcommands

    class Session:
        pass

    assert slashcommands.dispatch_command(Session(), "help", "") == "continue"
    assert "Slash commands" in capsys.readouterr().out


def test_ask_scrubs_retained_record_but_not_live_history():
    """The RECORD (retained_text / retained_reply) is always scrubbed; the
    LIVE message history is rewritten only when the intent engine actually
    supplied replacements — unconditional masking used to mangle the very
    text the model was still holding (see the guard in Session.ask)."""
    from birkin.runtime import build_session

    secret = "secret=will-not-survive-retention"
    session = build_session({"provider": "codex-cli", "model": ""})

    def run(text, **_kwargs):
        session.agent.messages.extend([
            {"role": "user", "content": [{"type": "text", "text": text}]},
            {"role": "assistant", "content": [{"type": "tool_use", "input": {"x": secret}}]},
            {"role": "user", "content": [{"type": "tool_result", "content": secret}]},
        ])
        return secret

    session.agent.run = run

    # Ordinary turn: live history untouched, record scrubbed.
    assert session.ask(secret) == secret
    assert secret in json.dumps(session.agent.messages)
    assert secret not in session.retained_text
    assert secret not in session.retained_reply

    # Intent-rewritten turn: the replacements reach the live history too.
    session.agent.messages.clear()
    assert session.ask(secret,
                       retained_replacements=((secret, "[redacted]"),)) == secret
    assert secret not in json.dumps(session.agent.messages)
    assert secret not in session.retained_text
    assert secret not in session.retained_reply
