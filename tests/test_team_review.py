from __future__ import annotations

import json
from pathlib import Path

import pytest

from birkin.team_review import add_comment, create_handoff, execute_share, list_review


class FakeDrive:
    def __init__(self, etag: str = "etag-1") -> None:
        self.etag = etag
        self.calls = []

    def request(self, method, path, body=None, *, headers=None):
        self.calls.append((method, path, body))
        if method == "GET":
            return {"id": "drive-1", "name": "report.docx", "eTag": self.etag}
        return {"value": [{"id": "permission-1", "roles": body["roles"]}]}


def test_review_handoff_binds_version_identity_and_permissions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    review = create_handoff({
        "drive_item_id": "drive-1", "source_etag": "etag-1", "source_name": "report.docx",
        "proposer": "owner@example.com", "reviewers": ["reviewer@example.com"], "role": "read", "message": "검토 부탁드립니다.",
    })
    graph = FakeDrive()
    shared = json.loads(execute_share(review, approval_id=None, client=graph))
    assert shared["status"] == "shared"
    assert graph.calls[-1][2]["requireSignIn"] is True and graph.calls[-1][2]["roles"] == ["read"]

    comment = add_comment({"review_id": review["id"], "actor": "reviewer@example.com", "text": "2쪽 수정"}, client=graph)
    assert comment["source_etag"] == "etag-1"
    assert list_review(review["id"], "owner@example.com")["comments"][0]["text"] == "2쪽 수정"
    with pytest.raises(PermissionError):
        list_review(review["id"], "stranger@example.com")


def test_review_refuses_changed_source_for_share_and_comment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    review = create_handoff({
        "drive_item_id": "drive-1", "source_etag": "etag-1", "source_name": "report.docx",
        "proposer": "owner@example.com", "reviewers": ["reviewer@example.com"],
    })
    changed = FakeDrive("etag-2")
    with pytest.raises(ValueError, match="version changed"):
        execute_share(review, approval_id=None, client=changed)
    with pytest.raises(ValueError, match="older version"):
        add_comment({"review_id": review["id"], "actor": "reviewer@example.com", "text": "comment"}, client=changed)
