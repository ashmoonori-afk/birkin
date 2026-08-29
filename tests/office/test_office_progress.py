from __future__ import annotations

import pytest

from birkin.office.job_types import OfficeJobState
from birkin.office.progress import office_progress_payload


@pytest.mark.parametrize(
    ("state", "phase", "status", "ui_state"),
    [
        (OfficeJobState.input_captured, "inspection", "working", "pending"),
        (OfficeJobState.operations_proposed, "comparison", "working", "pending"),
        (OfficeJobState.approved, "draft", "working", "pending"),
        (OfficeJobState.validated, "validation", "working", "pending"),
        (OfficeJobState.exported, "export", "succeeded", "succeeded"),
    ],
)
def test_office_progress_payload_maps_user_visible_stages(
    state: OfficeJobState,
    phase: str,
    status: str,
    ui_state: str,
) -> None:
    payload = office_progress_payload("job-progress", state)

    assert payload is not None
    assert payload["progress_id"] == "office:job-progress"
    assert payload["runtime_event"] == f"office.{phase}"
    assert payload["office_phase"] == phase
    assert payload["job_id"] == "job-progress"
    assert payload["status"] == status
    assert payload["ui_state"] == ui_state
    assert isinstance(payload["summary"], str)
    assert payload["summary"]


@pytest.mark.parametrize(
    "state",
    [
        OfficeJobState.outcome_declared,
        OfficeJobState.preview_ready,
        OfficeJobState.approval_requested,
        OfficeJobState.executed,
        OfficeJobState.rejected,
        OfficeJobState.failed,
    ],
)
def test_office_progress_payload_omits_duplicate_internal_states(
    state: OfficeJobState,
) -> None:
    assert office_progress_payload("job-progress", state) is None
