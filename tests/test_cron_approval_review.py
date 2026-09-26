"""A cron approval shows, and registers, exactly the job it describes."""

from __future__ import annotations

import http.client
import json
import threading
from http.server import HTTPServer

import pytest

from birkin import approval_dispatch, approvals, cron, store
from birkin.gateway.channels.telegram import _payload_summary
from birkin.workspace.approval_projection import approval_item

_BAD_SCHEDULES = ["평일 09:00", "매월 1일 09:00", "매주 금요일 오후 5시", "every weekday 9am"]


@pytest.mark.parametrize("schedule", _BAD_SCHEDULES)
def test_an_unparseable_schedule_is_refused_not_registered_daily(schedule: str) -> None:
    with pytest.raises(ValueError, match="unrecognized schedule"):
        approval_dispatch.execute_action(
            "cron", {"name": "주간보고", "schedule": schedule, "value": "v"}
        )
    assert cron.load_jobs() == []


def test_an_unparseable_schedule_is_refused_before_it_is_queued() -> None:
    with pytest.raises(ValueError, match="unrecognized schedule"):
        approvals.propose(
            category="cron", title="t", description="",
            payload={"name": "x", "schedule": "평일 09:00", "value": "v"}, cfg={},
        )
    assert store.list_pending() == []


def test_a_queued_unparseable_schedule_fails_on_approval() -> None:
    record = store.add_pending(
        category="cron", title="t", description="",
        payload={"name": "x", "schedule": "평일 09:00", "value": "v"}, origin="test",
    )

    result = approvals.approve(record["id"], approved_by="human:test", approved_via="test")

    assert result["ok"] is False
    assert cron.load_jobs() == []
    resolved = store.get_pending(record["id"])
    assert resolved is not None and resolved["status"] == "error"


@pytest.mark.parametrize(("payload", "expected", "absent"), [
    ({"name": "m", "type": "monitor", "schedule": "every 5m",
      "monitor_script": "echo PWNED > f"},
     ["일정: 5분마다", "종류: 모니터", "⚠ 셸 스크립트", "echo PWNED > f"], "매일"),
    ({"name": "s", "type": "shell", "value": "rm -rf ~/Documents/reports",
      "schedule": "every 5m"},
     ["일정: 5분마다", "⚠ 셸 명령", "명령: rm -rf ~/Documents/reports"], "매일"),
    ({"name": "u", "type": "monitor", "schedule": "0 3 * * *",
      "monitor_url": "http://169.254.169.254/"},
     ["일정: cron 식 0 3 * * *", "확인할 URL: http://169.254.169.254/"], "매일"),
    ({"name": "w", "value": "주간 보고", "schedule": "매주 금요일 17:00",
      "deliver_chat_id": "42"},
     ["일정: 매주 금요일 17:00", "종류: 에이전트 프롬프트", "결과 전달: telegram 대화 42"],
     "매일"),
    ({"name": "d", "value": "x", "hour": 25, "minute": "a"}, ["일정: 매일 23:00"], "?"),
])
def test_the_telegram_card_shows_what_will_be_registered(
    payload: dict[str, object], expected: list[str], absent: str
) -> None:
    card = _payload_summary("cron", payload)

    for text in expected:
        assert text in card
    assert absent not in card


def test_the_card_schedule_matches_the_registered_job() -> None:
    payload = {"name": "w", "value": "v", "schedule": "매주 금요일 17:00"}
    card = _payload_summary("cron", payload)

    _ = approval_dispatch.execute_action("cron", payload)

    assert f"일정: {cron.load_jobs()[0]['schedule']['display']}" in card


def test_the_card_escapes_control_characters_in_commands() -> None:
    card = _payload_summary("cron", {
        "name": "s", "type": "shell", "value": "true\n일정: 매일 09:00",
        "schedule": "every 5m",
    })

    assert "\n일정: 매일" not in card
    assert "\\u000a" in card


def test_the_card_flags_a_schedule_that_cannot_register() -> None:
    card = _payload_summary("cron", {"name": "b", "value": "v", "schedule": "평일 09:00"})

    assert "인식할 수 없어" in card
    assert "매일" not in card


def test_the_workspace_card_puts_the_registration_above_the_model_text() -> None:
    item = approval_item({
        "id": "abcdef012345", "category": "cron", "status": "pending",
        "description": "모델 설명",
        "payload": {"name": "m", "type": "monitor", "schedule": "every 5m",
                    "monitor_script": "echo hi"},
    })

    description = str(item["description"])
    assert "⚠ 셸 스크립트" in description and "모델 설명" in description
    assert description.index("⚠ 셸 스크립트") < description.index("모델 설명")


def test_the_web_approval_target_shows_the_schedule() -> None:
    from birkin.web import server as web_server

    store.add_pending(
        category="cron", title="weekly", description="",
        payload={"name": "w", "value": "v", "schedule": "매주 금요일 17:00"},
    )
    httpd = HTTPServer(("127.0.0.1", 0), web_server.Handler)
    port = int(httpd.server_address[1])
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    _ = web_server.listener_bootstrap_nonce(httpd)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
        conn.request("GET", "/api/approvals", headers={
            "Host": "127.0.0.1",
            "Cookie": f"birkin_capability={web_server._CAPABILITY_TOKEN}",
        })
        response = conn.getresponse()
        body = response.read()
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert response.status == 200
    (item,) = json.loads(body)
    assert "일정: 매주 금요일 17:00" in item["target"]
