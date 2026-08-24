from __future__ import annotations

from tests.office.test_office_job import _advance_to_approval, _job, _request


def test_receipt_has_fixed_keys_and_pending_values_are_none() -> None:
    job, _runner = _job()
    initial = job.receipt()
    expected_keys = {
        "job_id",
        "format",
        "state",
        "history",
        "outcome",
        "operations",
        "preview",
        "approval",
        "execution",
        "validation",
        "publication",
        "export",
        "rollback",
    }
    assert set(initial) == expected_keys
    assert initial == {
        "job_id": "job-1",
        "format": "docx",
        "state": "input_captured",
        "history": ["input_captured"],
        "outcome": None,
        "operations": None,
        "preview": None,
        "approval": None,
        "execution": None,
        "validation": None,
        "publication": None,
        "export": None,
        "rollback": None,
    }

    _advance_to_approval(job)
    job.approve(actor="reviewer")
    job.execute()
    job.validate()
    job.publish(output_name="final.docx")
    job.export(_request())
    completed = job.receipt()

    assert set(completed) == expected_keys
    assert completed["state"] == "exported"
    assert completed["outcome"] == "Replace the heading"
    assert completed["operations"] == [{"type": "replace_text", "value": "New"}]
    assert completed["preview"] is not None
    assert completed["execution"] is not None
    assert completed["validation"] is not None
    assert completed["publication"] is not None
    assert completed["export"] is not None
    assert completed["rollback"] is None
    approval = completed["approval"]
    assert isinstance(approval, dict)
    assert set(approval) == {"decision", "actor", "at", "proposal_digest"}
    assert approval["decision"] == "approved"
    assert approval["actor"] == "reviewer"
    assert isinstance(approval["at"], str)
    assert isinstance(approval["proposal_digest"], str)
