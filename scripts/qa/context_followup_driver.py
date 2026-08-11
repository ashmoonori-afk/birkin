from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import types
from collections.abc import Callable
from pathlib import Path

from birkin.gateway import core as gateway_core


def _fake_session():
    agent = types.SimpleNamespace(messages=[])

    def ask(text, on_text=None, **_kwargs):
        agent.messages.append({
            "role": "user",
            "content": [{"type": "text", "text": text}],
        })
        return "ok"

    return types.SimpleNamespace(cfg={}, agent=agent, ask=ask)


def _config(*chat_ids: str) -> dict:
    return {
        "channels": {
            "telegram": {
                "allowed_chat_ids": list(chat_ids),
            },
        },
    }


def _prompt(session) -> str:
    return session.agent.messages[-1]["content"][0]["text"]


def _isolated_home(run: Callable[[], dict]) -> dict:
    home = Path(tempfile.mkdtemp(prefix="birkin-context-followup-"))
    previous_home = os.environ.get("BIRKIN_HOME")
    os.environ["BIRKIN_HOME"] = str(home)
    try:
        result = run()
    finally:
        if previous_home is None:
            os.environ.pop("BIRKIN_HOME", None)
        else:
            os.environ["BIRKIN_HOME"] = previous_home
        shutil.rmtree(home)
    result["temp_home_removed"] = not home.exists()
    return result


def _with_sessions(sessions: list, run: Callable[[], dict]) -> dict:
    original = gateway_core.build_session
    remaining = iter(sessions)
    gateway_core.build_session = lambda cfg: next(remaining)
    try:
        return run()
    finally:
        gateway_core.build_session = original


def _happy(chat_id: str, first: str, followup: str) -> dict:
    session = _fake_session()

    def run() -> dict:
        gateway = gateway_core.Gateway(_config(chat_id))
        gateway.handle("telegram", chat_id, first)
        gateway.handle("telegram", chat_id, followup)
        prompt = _prompt(session)
        return {
            "anchor_source": (
                "previous_user_request"
                if "<conversation-followup-context>" in prompt
                else None
            ),
            "anchor_contains": "EBUSY" if "EBUSY" in prompt else None,
            "chat_id": chat_id,
            "followup": followup,
        }

    return _isolated_home(lambda: _with_sessions([session], run))


def _isolation() -> dict:
    session = _fake_session()

    def run() -> dict:
        gateway = gateway_core.Gateway(_config("42", "99"))
        gateway.handle("telegram", "42", "npm 설치가 EBUSY로 실패했어")
        gateway.handle("telegram", "99", "파이썬 데코레이터가 뭐야?")
        gateway.handle("telegram", "42", "쉽게 설명해")
        chat_42 = _prompt(session)
        gateway.handle("telegram", "99", "쉽게 설명해")
        chat_99 = _prompt(session)
        new_topic = "파이썬 데코레이터를 쉽게 설명해"
        gateway.handle("telegram", "42", new_topic)
        explicit_prompt = _prompt(session)
        return {
            "cross_chat_leak": (
                "데코레이터가 뭐야?" in chat_42
                or "EBUSY로 실패했어" in chat_99
            ),
            "explicit_topic_unchanged": (
                "<conversation-followup-context>" not in explicit_prompt
                and explicit_prompt.endswith(new_topic)
            ),
        }

    return _isolated_home(lambda: _with_sessions([session], run))


def _restart() -> dict:
    first_session = _fake_session()
    restarted_session = _fake_session()

    def run() -> dict:
        cfg = _config("42")
        first_gateway = gateway_core.Gateway(cfg)
        first_gateway.handle(
            "telegram",
            "42",
            "npm i -g omo-ai@beta가 EBUSY로 실패했어. 왜 뜨는 거야?",
        )
        saved_followup = "간단히 설명해"
        first_gateway.handle("telegram", "42", saved_followup)
        restarted_gateway = gateway_core.Gateway(cfg)
        followup = "쉽게 설명해"
        restarted_gateway.handle("telegram", "42", followup)
        prompt = _prompt(restarted_session)
        return {
            "restored_anchor_contains": "EBUSY" if "EBUSY" in prompt else None,
            "followup": followup,
            "skipped_saved_followup": (
                f"<previous-user-request>\n{saved_followup}\n"
                "</previous-user-request>" not in prompt
            ),
            "anchor_source": (
                "previous_user_request"
                if "<conversation-followup-context>" in prompt
                else None
            ),
        }

    return _isolated_home(
        lambda: _with_sessions([first_session, restarted_session], run),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exercise Birkin Telegram follow-up context handling.",
    )
    parser.add_argument("--chat-id", default="42")
    parser.add_argument("--first")
    parser.add_argument("--followup")
    parser.add_argument("--isolation-check", action="store_true")
    parser.add_argument("--restart-check", action="store_true")
    args = parser.parse_args()

    if args.isolation_check:
        result = _isolation()
    elif args.restart_check:
        result = _restart()
    elif args.first is not None and args.followup is not None:
        result = _happy(args.chat_id, args.first, args.followup)
    else:
        parser.error("--first and --followup are required for the happy path")

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
