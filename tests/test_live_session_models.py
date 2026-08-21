"""Tests for immutable live-session report models."""

from __future__ import annotations

from dataclasses import fields, replace

import pytest

from birkin.live_session_models import (
    LiveAgentProcess,
    LiveInventory,
    LiveProject,
    LiveScan,
    LiveSessionFile,
    Observation,
    ProcessField,
    ReadFailure,
    RefusalCounts,
    ScanCounters,
)


def _no_refusals() -> RefusalCounts:
    return RefusalCounts(
        name=0,
        cmdline=0,
        cwd=0,
        open_files=0,
    )


@pytest.mark.parametrize(
    ("value", "failure"),
    [
        ("available", ReadFailure.ACCESS_DENIED),
        (None, None),
    ],
)
def test_observation_requires_exactly_one_outcome(
    value: str | None,
    failure: ReadFailure | None,
) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        Observation(value=value, failure=failure)


def test_successful_empty_observations_use_concrete_values() -> None:
    empty_text = Observation(value="", failure=None)
    empty_files = Observation[tuple[LiveSessionFile, ...]](
        value=(),
        failure=None,
    )

    assert empty_text.value == ""
    assert empty_text.failure is None
    assert empty_files.value == ()
    assert empty_files.failure is None


def test_failed_observation_has_no_value() -> None:
    observation = Observation[str](
        value=None,
        failure=ReadFailure.PROCESS_GONE,
    )

    assert observation.value is None
    assert observation.failure is ReadFailure.PROCESS_GONE


def test_refusal_counts_nonzero_uses_fixed_process_field_order() -> None:
    refusals = RefusalCounts(
        name=2,
        cmdline=3,
        cwd=4,
        open_files=5,
    )

    assert refusals.total == 14
    assert refusals.nonzero() == (
        (ProcessField.NAME, 2),
        (ProcessField.CMDLINE, 3),
        (ProcessField.CWD, 4),
        (ProcessField.OPEN_FILES, 5),
    )


def test_refusal_counts_nonzero_is_empty_when_all_counts_are_zero() -> None:
    refusals = _no_refusals()

    assert refusals.total == 0
    assert refusals.nonzero() == ()


@pytest.mark.parametrize(
    "field",
    [
        "enumerated",
        "own_user",
        "unidentified",
        "cmdline_ok",
        "open_files_ok",
        "disappeared",
    ],
)
def test_scan_counters_reject_negative_counts(field: str) -> None:
    counters = ScanCounters(
        enumerated=0,
        own_user=0,
        unidentified=0,
        cmdline_ok=0,
        open_files_ok=0,
        disappeared=0,
        refusals=_no_refusals(),
    )

    with pytest.raises(ValueError, match="non-negative"):
        replace(counters, **{field: -1})


@pytest.mark.parametrize(
    "field",
    ["name", "cmdline", "cwd", "open_files"],
)
def test_refusal_counts_reject_negative_counts(field: str) -> None:
    refusals = _no_refusals()

    with pytest.raises(ValueError, match="non-negative"):
        replace(refusals, **{field: -1})


def test_report_models_have_no_freeform_limitation_field() -> None:
    prohibited = {"warning", "note", "caveat", "limitation", "message"}
    report_types = (
        LiveSessionFile,
        LiveAgentProcess,
        RefusalCounts,
        ScanCounters,
        LiveScan,
        LiveProject,
        LiveInventory,
    )

    for report_type in report_types:
        assert prohibited.isdisjoint(field.name for field in fields(report_type))
