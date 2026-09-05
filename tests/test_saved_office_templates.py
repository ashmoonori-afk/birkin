from __future__ import annotations

import json
from pathlib import Path

import pytest

from birkin import approvals
from birkin.office.saved_templates import apply_approved, list_templates, resolve
from birkin.tools import build_registry
from birkin.tools._types import ToolContext


def test_saved_template_is_approval_bound_versioned_and_body_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    registry = build_registry(ToolContext(cfg={}, client=None, cwd=tmp_path), include={"documents"})

    requested = registry.execute("office_template_request", {
        "action": "clone", "base": "weekly_report", "name": "팀 주간보고",
        "scope": "current_work", "preferences": {"tone": "formal"},
    })
    approval_id = json.loads(str(requested.content))["id"]
    assert list_templates(tmp_path)["saved"] == []
    assert approvals.approve(approval_id, approved_by="user:test", approved_via="test")["ok"] is True

    saved = list_templates(tmp_path)["saved"][0]
    assert "values" not in saved and "body" not in saved
    version_one = resolve(saved["id"], 1, {"title": "Q3", "period": "Sep", "summary": "Done"}, {}, tmp_path)
    apply_approved({"action": "update", "template_id": saved["id"], "version": 1,
                    "preferences": {"tone": "concise", "include_optional": False}, "workspace": str(tmp_path)})

    assert version_one["saved_template"]["version"] == 1
    with pytest.raises(ValueError, match="changed"):
        resolve(saved["id"], 1, {}, {}, tmp_path)
    with pytest.raises(ValueError, match="document body"):
        apply_approved({"action": "update", "template_id": saved["id"], "version": 2,
                        "preferences": {"body": "secret"}, "workspace": str(tmp_path)})

    restored = json.loads(apply_approved({
        "action": "restore", "template_id": saved["id"], "version": 2, "workspace": str(tmp_path),
    }))
    assert restored["version"] == 3
    assert restored["preferences"] == {"tone": "plain", "include_optional": True}
