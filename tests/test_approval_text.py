"""Korean approval presentation: stable machine results in, bounded copy out.

The stable English errors in approval_execution*.py stay the machine contract;
every surface renders them through birkin.approval_text. These tests pin the
typed fields (code, tone, ui_state) and the rule that raw error text, receipt
JSON and paths never become the summary, and that only a real success can
carry a check mark.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from birkin import approval_dispatch, approval_text, risk

_HANGUL = re.compile(r"[\uac00-\ud7a3]")

_STABLE_ERRORS = [
    ("invalid approval id", "E_APPROVAL_INVALID_ID"),
    ("not found or already resolved", "E_APPROVAL_ALREADY_RESOLVED"),
    ("approval is not claimed", "E_APPROVAL_NOT_CLAIMED"),
    ("structured action requires answers", "E_APPROVAL_NEEDS_ANSWERS"),
    ("Telegram workflow requires its origin chat", "E_APPROVAL_WORKFLOW_ORIGIN"),
    ("approval store is busy", "E_APPROVAL_STORE_BUSY"),
    ("cron store is busy; retry.", "E_APPROVAL_STORE_BUSY"),
    ("cron store is busy", "E_APPROVAL_STORE_BUSY"),
    ("approval store is unavailable: [Errno 5] I/O error", "E_APPROVAL_STORE_UNAVAILABLE"),
    ("approval payload is malformed", "E_APPROVAL_PAYLOAD_MALFORMED"),
    ("approval execution could not be armed: journal broken", "E_APPROVAL_INTEGRITY"),
    ("approval execution state is missing", "E_APPROVAL_INTEGRITY"),
    ("approval execution authority was changed", "E_APPROVAL_INTEGRITY"),
    ("Office approval authority is incomplete", "E_APPROVAL_INTEGRITY"),
    ("execution frozen", "E_APPROVAL_INTEGRITY"),
    ("action outcome is unknown", "E_APPROVAL_OUTCOME_UNKNOWN"),
    ("approval helper exited with status 3", "E_APPROVAL_HELPER_EXITED"),
    ("action recovery required: lost", "E_APPROVAL_FINALIZE_PENDING"),
    ("action committed; approval finalization is pending: x", "E_APPROVAL_FINALIZE_PENDING"),
    ("action outcome persistence failed: disk", "E_APPROVAL_FINALIZE_PENDING"),
    ("continuation is not pending", "E_APPROVAL_CONTINUATION_FAILED"),
    ("continuation failed: worker gone", "E_APPROVAL_CONTINUATION_FAILED"),
    ("action failed: unknown approval category 'bogus'", "E_APPROVAL_ACTION_FAILED"),
    ("something nobody mapped", "E_APPROVAL_UNKNOWN"),
]


@pytest.mark.parametrize(("error", "code"), _STABLE_ERRORS)
def test_every_stable_error_maps_to_korean_failure_copy(error: str, code: str) -> None:
    outcome = approval_text.error_outcome(error)
    rendered = outcome.render()

    assert outcome.code == code
    assert outcome.tone == "failure"
    assert outcome.ok is False
    assert _HANGUL.search(outcome.summary)
    assert error not in rendered
    assert "✅" not in rendered
    assert "✓" not in outcome.render(marks=approval_text.TERMINAL_MARKS)


def test_an_armed_error_never_leaks_its_os_detail() -> None:
    outcome = approval_text.error_outcome(
        "approval execution could not be armed: /secret/path"
    )
    assert "/secret/path" not in outcome.render()
    assert outcome.code == "E_APPROVAL_INTEGRITY"


def test_outcome_unknown_asks_the_user_to_act() -> None:
    assert approval_text.error_outcome("action outcome is unknown").ui_state == (
        "action_needed"
    )


def test_a_follow_up_result_points_to_the_new_request() -> None:
    outcome = approval_text.error_outcome(
        {"ok": False, "error": "기존 파일을 덮어쓸까요?", "follow_up_approval_id": "a" * 12}
    )
    assert (outcome.code, outcome.ui_state) == ("follow_up_required", "action_needed")
    assert outcome.summary == approval_text.FOLLOW_UP


def test_an_unconfirmed_mail_send_keeps_its_mail_copy() -> None:
    from birkin.approval_mail_outcome import unconfirmed_response

    result = unconfirmed_response("accepted")
    outcome = approval_text.approve_outcome({"status": "action_outcome_unknown"}, result)

    assert outcome.code == "E_APPROVAL_OUTCOME_UNKNOWN"
    assert outcome.ok is False
    assert outcome.summary == result["error"]
    assert outcome.ui_state == "action_needed"


# -- approve results -----------------------------------------------------------


def test_a_zero_exit_is_the_only_shell_success() -> None:
    outcome = approval_text.approve_outcome(None, {"ok": True, "result": "[exit 0] hi"})
    assert outcome.ok is True
    assert "hi" in outcome.detail
    assert outcome.render(marks=approval_text.TERMINAL_MARKS).startswith("✓")


def test_a_cut_command_output_says_it_was_cut() -> None:
    result = {"ok": True, "result": "[exit 0] " + "가" * 1000}

    short = approval_text.approve_outcome(None, result)
    long = approval_text.approve_outcome(None, result, output_chars=3200)

    assert "가" * 300 in short.detail and "가" * 301 not in short.detail
    assert "전체 1000자 중 300자만 표시" in short.detail
    assert "가" * 1000 in long.detail and "자만 표시" not in long.detail


def test_a_replayed_operation_output_is_the_detail() -> None:
    outcome = approval_text.approve_outcome(
        {"category": "operation", "status": "approved"},
        {"ok": True, "result": "파일 내용"},
    )

    assert (outcome.ok, outcome.summary) == (True, "승인한 작업을 완료했습니다.")
    assert outcome.detail == "출력: 파일 내용"


def test_a_nonzero_exit_is_a_failure() -> None:
    outcome = approval_text.approve_outcome(None, {"ok": True, "result": "[exit 3] "})
    assert (outcome.code, outcome.ok) == ("command_failed", False)
    assert "3" in outcome.summary
    assert outcome.render(marks=approval_text.TERMINAL_MARKS).startswith("✗")


@pytest.mark.parametrize(
    ("result", "code"),
    [
        (approval_dispatch.SHELL_TIMEOUT_RESULT, "command_timed_out"),
        (approval_dispatch.SHELL_EMPTY_RESULT, "command_empty"),
        (f"{approval_dispatch.SHELL_CWD_MISSING_PREFIX} /secret/cwd", "command_cwd_missing"),
    ],
)
def test_shell_results_that_ran_nothing_are_failures(result: str, code: str) -> None:
    outcome = approval_text.approve_outcome(None, {"ok": True, "result": result})
    assert (outcome.code, outcome.ok) == (code, False)
    assert "/secret/cwd" not in outcome.render()


def test_a_replayed_operation_exit_reads_as_a_command_failure() -> None:
    outcome = approval_text.approve_outcome(
        None, {"ok": False, "error": "action failed: [exit 1]\nboom"}
    )
    assert (outcome.code, outcome.ok) == ("command_failed", False)
    assert "boom" in outcome.detail


def test_executor_text_is_not_the_summary() -> None:
    outcome = approval_text.approve_outcome(
        {"category": "cron", "status": "approved"},
        {"ok": True, "result": "Registered cron job 'x' at 09:00 (id abc)."},
    )
    assert outcome.ok is True
    assert "Registered" not in outcome.render()


def test_a_running_approval_is_progress_not_success() -> None:
    outcome = approval_text.approve_outcome(None, {"ok": True, "status": "executing"})
    assert (outcome.tone, outcome.ui_state) == ("progress", "running")
    assert outcome.ok is False


def test_a_workflow_receipt_is_delivered_as_the_detail() -> None:
    report = "✅ 워크플로우 완료 (hard-task)\n\n결과 본문\n\n실행 기록: r1"
    outcome = approval_text.approve_outcome(
        {"category": "moirai", "status": "approved"}, {"ok": True, "result": report}
    )
    assert outcome.ok is True
    assert "결과 본문" in outcome.detail

    failed = approval_text.approve_outcome(
        {"category": "moirai", "status": "approved"},
        {"ok": True, "result": "❌ 워크플로우 실패\n\n실행 기록: r2"},
    )
    assert (failed.code, failed.ok) == ("workflow_failed", False)


@pytest.mark.parametrize(
    ("run", "expected"),
    [
        ({"status": "completed", "completion": "partial", "failures": 3},
         ("failure", "workflow_partial", "action_needed")),
        ({"status": "waiting_input"},
         ("progress", "workflow_waiting", "action_needed")),
        ({"status": "aborted"}, ("failure", "workflow_failed", "failed")),
        ({"status": "completed", "result": "끝"}, ("success", "approved", "succeeded")),
    ],
)
def test_only_a_complete_workflow_carries_a_check_mark(
    run: dict[str, object], expected: tuple[str, str, str]
) -> None:
    from birkin.moirai import outcome as moirai_outcome

    report = moirai_outcome.render({**run, "run_id": "r3"}, name="hard")
    outcome = approval_text.approve_outcome(
        {"category": "moirai", "status": "approved"}, {"ok": True, "result": report}
    )
    rendered = outcome.render(marks=approval_text.TERMINAL_MARKS, limit=2400)

    assert (outcome.tone, outcome.code, outcome.ui_state) == expected
    assert outcome.detail == report
    assert rendered.startswith("✓") is (expected[0] == "success")


def test_an_unrecognised_workflow_receipt_is_not_a_success() -> None:
    outcome = approval_text.approve_outcome(
        {"category": "moirai", "status": "approved"},
        {"ok": True, "result": "moirai: hard-task completed — 에이전트 2"},
    )
    assert (outcome.tone, outcome.code, outcome.ok) == ("info", "workflow_unconfirmed", False)
    assert _HANGUL.search(outcome.summary)


def _office_record() -> dict[str, object]:
    return {
        "id": "abcdef012345",
        "category": "office_job",
        "status": "approved",
        "payload": {"job_id": "job-1"},
    }


def _office_receipt(*, valid: bool) -> str:
    return json.dumps({
        "publication": {"artifact": {"artifact_id": "art-1"}},
        "export": {
            "path": "/home/u/out/report.docx",
            "issued_at": "2026-09-26T00:00:00+00:00",
            "expires_at": "2026-10-26T00:00:00+00:00",
        },
        "validation": {"valid": valid, "layers": {"fidelity": {"status": "pass"}}},
    })


def test_an_office_receipt_reads_as_destination_and_validation() -> None:
    outcome = approval_text.approve_outcome(
        _office_record(), {"ok": True, "result": _office_receipt(valid=True)}
    )
    rendered = outcome.render()

    assert outcome.ok is True
    assert "/home/u/out/report.docx" in outcome.detail
    assert "구조 검증" in outcome.detail
    assert "{" not in rendered


def test_an_office_receipt_that_failed_validation_is_not_a_success() -> None:
    outcome = approval_text.approve_outcome(
        _office_record(), {"ok": True, "result": _office_receipt(valid=False)}
    )
    assert (outcome.code, outcome.ok) == ("office_validation_failed", False)


def test_a_malformed_office_receipt_falls_back_to_generic_copy() -> None:
    outcome = approval_text.approve_outcome(
        _office_record(), {"ok": True, "result": "{not json"}
    )
    assert (outcome.code, outcome.ok) == ("approved", True)
    assert "{" not in outcome.render()


# -- records resolved elsewhere ---------------------------------------------------


@pytest.mark.parametrize(
    ("status", "tone", "ui_state"),
    [
        ("approved", "info", "succeeded"),
        ("resume_pending", "info", "succeeded"),
        ("approving", "info", "running"),
        ("executing", "info", "running"),
        ("resuming", "info", "running"),
        ("rejected", "info", "blocked"),
        ("expired", "info", "blocked"),
        ("error", "failure", "failed"),
        ("execution_frozen", "failure", "failed"),
        ("action_outcome_unknown", "failure", "action_needed"),
        ("answered", "info", "succeeded"),
        ("consumed", "info", "succeeded"),
    ],
)
def test_resolved_elsewhere_names_the_state(status: str, tone: str, ui_state: str) -> None:
    outcome = approval_text.resolved_elsewhere({"status": status})
    assert (outcome.code, outcome.tone, outcome.ui_state) == (
        "answered_elsewhere",
        tone,
        ui_state,
    )
    assert _HANGUL.search(outcome.summary)
    assert outcome.ok is False


def test_resolved_elsewhere_names_the_surface() -> None:
    record = {"status": "approved", "approved_via": "gateway:telegram"}
    outcome = approval_text.approve_outcome(
        record, {"ok": False, "error": "not found or already resolved"}
    )
    assert approval_text.SURFACE_LABELS["gateway:telegram"] in outcome.summary
    assert outcome.code == "answered_elsewhere"


def test_an_unknown_resolved_status_is_already_resolved() -> None:
    assert approval_text.resolved_elsewhere({"status": "zzz"}).code == (
        "E_APPROVAL_ALREADY_RESOLVED"
    )


def test_reject_outcomes() -> None:
    assert approval_text.reject_outcome({"ok": True}, None).code == "rejected"
    elsewhere = approval_text.reject_outcome(
        {"ok": False}, {"status": "approved", "approved_via": "terminal:review"}
    )
    assert elsewhere.code == "answered_elsewhere"
    assert approval_text.SURFACE_LABELS["terminal"] in elsewhere.summary
    assert approval_text.reject_outcome({"ok": False}, None).code == (
        "E_APPROVAL_ALREADY_RESOLVED"
    )
    assert approval_text.reject_outcome({"ok": False}, {"status": "pending"}).code == (
        "E_APPROVAL_STORE_BUSY"
    )


def test_record_outcome_projects_resolved_records() -> None:
    failed = approval_text.record_outcome(
        {"status": "error", "execution_error": "action failed: boom"}
    )
    assert failed.code == "E_APPROVAL_ACTION_FAILED"
    assert "boom" not in failed.summary
    assert approval_text.record_outcome({"status": "rejected"}).code == "rejected"
    approved = approval_text.record_outcome(
        {"status": "approved", "category": "shell", "action_receipt": "[exit 2] no"}
    )
    assert (approved.code, approved.ok) == ("command_failed", False)


# -- labels and record helpers ------------------------------------------------------


def test_every_category_ships_with_a_label() -> None:
    assert set(risk.CATEGORY_RISK) | {"workflow", "question", "companion"} <= set(
        approval_text.CATEGORY_LABELS
    )
    assert set(risk.TIERS) <= set(approval_text.RISK_LABELS)


def test_headline_uses_labels_not_enums() -> None:
    line = approval_text.headline({"category": "cron", "title": ""})
    assert "[cron]" not in line
    assert approval_text.category_label("cron") in line
    assert approval_text.risk_label("medium") in line
    assert approval_text.category_label("bogus") == approval_text.UNKNOWN_CATEGORY_LABEL


def test_questions_need_answers() -> None:
    assert approval_text.needs_answers({"category": "question"})
    assert approval_text.needs_answers({"category": "moirai", "action_state": "action_needed"})
    assert not approval_text.needs_answers({"category": "shell"})


def test_request_target_is_bounded_and_secret_free() -> None:
    record = {
        "category": "operation",
        "payload": {"operation": {"input": {"command": "curl -H 'Bearer abcdef123'" + "x" * 400}}},
    }
    target = approval_text.request_target(record)
    assert "abcdef123" not in target
    assert len(target) <= 210
    assert approval_text.request_target(
        {"category": "shell", "payload": {"command": "ls -la"}}
    ) == "ls -la"


def test_operation_summary_keeps_review_critical_fields() -> None:
    payload = {
        "operation": {
            "version": 1,
            "tool": "run_shell",
            "input": {"command": "x" * 2000},
            "cwd": "C:/workspace",
            "gate": "powershell_execution_policy",
            "environment": {"PSExecutionPolicyPreference": "Bypass"},
        },
        "digest": "abcdef0123456789" * 4,
    }

    summary = approval_text.payload_summary("operation", payload)

    assert "run_shell" in summary
    assert "powershell_execution_policy" in summary
    assert "C:/workspace" in summary
    assert "PSExecutionPolicyPreference=Bypass" in summary
    assert "abcdef0123456789" in summary
    assert len(summary) < 3500
    assert approval_text.payload_summary("operation", {}) == (
        "↳ 요청 데이터가 올바르지 않습니다."
    )


def test_office_summary_shows_source_destination_and_overwrite() -> None:
    summary = approval_text.payload_summary(
        "office_job",
        {"source_filename": "매출.xlsx", "destination": "D:/out/report.docx",
         "overwrite_approved": False},
    )
    assert "매출.xlsx" in summary
    assert "D:/out/report.docx" in summary
    assert "덮어쓰기" in summary


def test_other_payloads_render_as_json_not_python_repr() -> None:
    summary = approval_text.payload_summary("bogus", {"flag": True, "name": "값"})
    assert "True" not in summary and "true" in summary
    assert "값" in summary
    assert approval_text.payload_summary("bogus", {"a": 1}, fallback=False) == ""


def test_payload_detail_is_bounded_only_when_asked() -> None:
    payload = {"command": "y" * 1000}
    assert len(approval_text.payload_detail(payload)) < 700
    assert "y" * 1000 in approval_text.payload_detail(payload, limit=None)


def test_a_malformed_continuation_is_described_not_raised() -> None:
    assert _HANGUL.search(approval_text.continuation_summary({"schema": 2}))


def test_gate_consequence_warns_about_shell_egress() -> None:
    text = approval_text.gate_consequence("tool_policy", "run_shell")
    assert "egress" in text
    assert "egress" not in approval_text.gate_consequence("tool_policy", "read_file")
    assert _HANGUL.search(approval_text.gate_consequence("unknown_gate", "x"))


# -- drift guard: dispatch results that ran nothing ----------------------------------


def test_dispatch_shell_results_that_ran_nothing_never_render_success(
    tmp_path: Path,
) -> None:
    def times_out(_command: object) -> object:
        raise subprocess.TimeoutExpired("sleep", 1)

    results = [
        approval_dispatch.execute_action("shell", {"command": ""}),
        approval_dispatch.execute_action(
            "shell",
            {"command": "sleep 5", "cwd": str(tmp_path)},
            approval_dispatch.DispatchOptions(shell_runner=times_out),
        ),
        approval_dispatch.execute_action(
            "shell", {"command": "true", "cwd": str(tmp_path / "missing")}
        ),
    ]

    for result in results:
        outcome = approval_text.approve_outcome(None, {"ok": True, "result": result})
        assert outcome.ok is False, result
