from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from birkin import approvals, config, store
from birkin.office.job_journal import OfficeJobJournal
from birkin.office.job_runner import DocumentServiceRunner
from birkin.office.job_types import OfficeJobState
from birkin.office.service import DocumentService
from tests.office.test_office_coordinator import _queue, _sha256


_CRASH_DRIVER = r"""
import os
import sys
from pathlib import Path
from birkin import approvals
from birkin.office.job_runner import DocumentServiceRunner

mode, approval_id, destination = sys.argv[1:]
if mode == "before_coordinator":
    def stop_before_coordinator(*args, **kwargs):
        os._exit(71)
    approvals.execute_action = stop_before_coordinator
elif mode == "after_execution":
    original = DocumentServiceRunner.execute
    def stop_after_execution(self, **kwargs):
        original(self, **kwargs)
        os._exit(72)
    DocumentServiceRunner.execute = stop_after_execution
elif mode == "after_destination_replace":
    original = os.replace
    wanted = Path(destination)
    def stop_after_replace(source, target):
        original(source, target)
        if Path(target) == wanted:
            os._exit(73)
    os.replace = stop_after_replace
else:
    os._exit(99)
approvals.approve(approval_id)
os._exit(98)
"""


@pytest.mark.parametrize(
    ("mode", "returncode"),
    [
        ("before_coordinator", 71),
        ("after_execution", 72),
        ("after_destination_replace", 73),
    ],
)
def test_real_process_crash_resumes_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    returncode: int,
) -> None:
    # Given: a real child process owns one approved Office mutation.
    body, record, source, destination, source_sha256 = _queue(tmp_path, monkeypatch)
    approval_id = cast(str, body["id"])
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[2])}

    # When: it hard-exits at a durable boundary and a fresh process resumes it.
    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            _CRASH_DRIVER,
            mode,
            approval_id,
            str(destination),
        ],
        cwd=Path(__file__).parents[2],
        env=environment,
        check=False,
    )
    assert crashed.returncode == returncode
    pending = store.get_pending(approval_id)
    assert pending is not None
    assert pending["status"] == "executing"
    result = approvals.approve(approval_id)

    # Then: one exported receipt survives, source stays immutable, and no phase repeats.
    assert result["ok"] is True, result
    payload = cast("dict[str, object]", record["payload"])
    runner = DocumentServiceRunner(
        DocumentService(config.birkin_home()),
        export_root=Path(cast(str, payload["allowlist_root"])),
    )
    job = OfficeJobJournal(config.birkin_home() / "office" / "jobs").restore(
        cast(str, payload["job_id"]), runner=runner
    )
    assert job.state is OfficeJobState.exported
    assert job.history.count(OfficeJobState.approved) == 1
    assert job.history.count(OfficeJobState.executed) == 1
    assert job.history.count(OfficeJobState.exported) == 1
    assert _sha256(source) == source_sha256
    assert destination.is_file()
