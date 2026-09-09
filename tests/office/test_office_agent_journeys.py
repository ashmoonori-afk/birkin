from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_five_office_agent_journeys_emit_verified_private_metrics(tmp_path: Path) -> None:
    script = Path(__file__).parents[2] / "script" / "qa" / "office_agent_journeys.py"
    run = subprocess.run([sys.executable, str(script), "--output-dir", str(tmp_path / "journeys")],
                         cwd=script.parents[2], text=True, capture_output=True, check=False)
    assert run.returncode == 0, run.stderr or run.stdout
    report = json.loads(run.stdout)
    assert report["ok"] is True and set(report["journeys"]) == {
        "first_docx", "existing_xlsx_edit", "pdf_to_docx_summary", "meeting_to_tasks", "mail_draft_review",
    }
    assert len(report["metrics"]) == 5
    assert all(set(item) == {"journey", "time_to_first_result_ms", "unnecessary_questions", "manual_edits",
                             "recovery_attempts", "recovery_successes", "recovery_success_rate"} for item in report["metrics"])
    assert sum(item["recovery_successes"] for item in report["metrics"]) == 2
