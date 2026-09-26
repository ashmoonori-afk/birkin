"""Korean review lines for a cron proposal, built from what will be registered.

A cron approval card must show the job ``cron.add_job`` will actually store,
not the model's own summary: the schedule, the action type and the full
command, script or URL. Every line is derived from
``approval_dispatch.cron_registration``, the same normalisation execution uses.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Final

from . import approval_dispatch, cron
from .tools.connections import visible_text

_TYPE_LABELS: Final = {
    "prompt": "에이전트 프롬프트",
    "briefing": "브리핑",
    "shell": "⚠ 셸 명령 (승인하면 무인으로 반복 실행됩니다)",
    "monitor": "모니터",
}
_PREVIEW_CHARS: Final = 600


def _preview(value: object) -> str:
    # Control and format characters are escaped so a command cannot fake the
    # following review lines or flip how the text reads.
    text = visible_text(value)
    if len(text) <= _PREVIEW_CHARS:
        return text
    return f"{text[:_PREVIEW_CHARS]}… (전체 {len(text)}자 중 일부)"


def _span(minutes: int) -> str:
    if minutes % 1440 == 0:
        return f"{minutes // 1440}일"
    if minutes % 60 == 0:
        return f"{minutes // 60}시간"
    return f"{minutes}분"


def schedule_text(schedule: str | None, hour: int, minute: int) -> str:
    """Korean text for the schedule ``cron.add_job`` will store.

    Cron expressions are never translated freely: a weekly Korean form shows
    its own display, any other expression is shown as the expression itself.
    """
    parsed = cron.parse_schedule(schedule) if schedule else None
    if parsed is None:
        return f"매일 {hour:02d}:{minute:02d}"
    kind = parsed["kind"]
    if kind == "daily":
        return f"매일 {int(parsed['hour']):02d}:{int(parsed['minute']):02d}"
    if kind == "interval":
        return f"{_span(int(parsed['minutes']))}마다"
    if kind == "once":
        relative = cron.parse_duration(
            str(schedule).strip().removesuffix("후").strip()
        )
        if relative is not None:
            return f"승인 시점부터 {_span(relative)} 뒤 1회"
        return f"1회 · {str(parsed['run_at']).replace('T', ' ')[:16]}"
    display = str(parsed.get("display") or "")
    expr = str(parsed.get("expr") or "")
    return display if display and display != expr else f"cron 식 {expr}"


def cron_review_lines(payload: Mapping[str, object]) -> list[str]:
    """What an approved cron payload will register, never the model's summary."""
    try:
        job = approval_dispatch.cron_registration(dict(payload))
    except ValueError:
        return [
            f"⚠ 일정 '{_preview(payload.get('schedule'))}'을(를) 인식할 수 없어 "
            "승인해도 등록되지 않습니다"
        ]
    action_type = str(job["action_type"])
    label = _TYPE_LABELS.get(action_type)
    if label is None:
        raw = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, default=str)
        return [
            f"⚠ 알 수 없는 작업 종류 '{_preview(action_type)}'",
            f"요청 데이터: {_preview(raw)}",
        ]
    lines = [
        f"예약 작업: {_preview(job['name'])}",
        f"일정: {schedule_text(job['schedule'], job['hour'], job['minute'])}",
        f"종류: {label}",
    ]
    if job["monitor_script"]:
        lines.append(
            "⚠ 셸 스크립트 (승인하면 무인으로 반복 실행됩니다): "
            + _preview(job["monitor_script"])
        )
    if job["monitor_url"]:
        lines.append(f"확인할 URL: {_preview(job['monitor_url'])}")
    if job["value"]:
        field = "명령" if action_type == "shell" else "내용"
        lines.append(f"{field}: {_preview(job['value'])}")
    if job["deliver_chat_id"]:
        channel = str(job["deliver_channel"]).strip().lower()
        lines.append(
            f"결과 전달: {visible_text(channel)} 대화 "
            f"{visible_text(job['deliver_chat_id'])}"
        )
    return lines


__all__ = ["cron_review_lines", "schedule_text"]
