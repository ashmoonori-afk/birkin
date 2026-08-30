"""Canonical user-facing progress for Office job transitions."""

from __future__ import annotations

from collections.abc import Callable

from .job import OfficeJobTransitionSink
from .job_types import OfficeJobState

RuntimeEventSink = Callable[[str, dict[str, object]], None]

_STAGES: dict[OfficeJobState, tuple[str, str, str, str]] = {
    OfficeJobState.input_captured: (
        "inspection",
        "문서 검사를 완료했습니다.",
        "working",
        "pending",
    ),
    OfficeJobState.operations_proposed: (
        "comparison",
        "변경 전후를 비교하고 있습니다.",
        "working",
        "pending",
    ),
    OfficeJobState.approved: (
        "draft",
        "승인된 초안을 만들고 있습니다.",
        "working",
        "pending",
    ),
    OfficeJobState.validated: (
        "validation",
        "초안 검증을 완료했습니다.",
        "working",
        "pending",
    ),
    OfficeJobState.exported: (
        "export",
        "문서 내보내기를 완료했습니다.",
        "succeeded",
        "succeeded",
    ),
}


def office_progress_payload(
    job_id: str,
    state: OfficeJobState,
) -> dict[str, object] | None:
    """Return one stable progress payload for user-visible Office stages."""
    stage = _STAGES.get(state)
    if stage is None:
        return None
    phase, summary, status, ui_state = stage
    return {
        "progress_id": f"office:{job_id}",
        "runtime_event": f"office.{phase}",
        "office_phase": phase,
        "job_id": job_id,
        "summary": summary,
        "status": status,
        "ui_state": ui_state,
    }


def office_progress_sink(
    on_event: RuntimeEventSink | None,
) -> OfficeJobTransitionSink | None:
    """Adapt Office transitions to the runtime event sink contract."""
    if on_event is None:
        return None

    def emit(job_id: str, state: OfficeJobState) -> None:
        payload = office_progress_payload(job_id, state)
        if payload is not None:
            on_event("office_progress", payload)

    return emit
