"""Tests for the workflow CRUD API routes."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from birkin.core.session import SessionStore
from birkin.gateway.app import create_app
from birkin.gateway.deps import (
    reset_session_store,
    reset_wiki_memory,
    set_session_store,
    set_wiki_memory,
)
from birkin.memory.wiki import WikiMemory


@pytest.fixture(autouse=True)
def _clean_deps(tmp_path):
    """Inject fresh session store and wiki memory for each test."""
    db_file = tmp_path / "test_sessions.db"
    set_session_store(SessionStore(db_path=db_file))

    wiki_dir = tmp_path / "wiki_memory"
    wiki = WikiMemory(root=wiki_dir)
    wiki.init()
    set_wiki_memory(wiki)

    yield

    reset_wiki_memory()
    reset_session_store()


@pytest.fixture(autouse=True)
def _isolate_workflows(tmp_path):
    """Redirect workflow persistence to a temp file so tests don't pollute the project."""
    wf_path = tmp_path / "birkin_workflows.json"
    with patch("birkin.gateway.workflows._WORKFLOWS_PATH", wf_path):
        yield


@pytest.fixture()
def client(_clean_deps, _isolate_workflows):
    app = create_app()
    return TestClient(app)


class TestWorkflowList:
    def test_list_returns_samples_and_empty_saved(self, client: TestClient):
        resp = client.get("/api/workflows")
        assert resp.status_code == 200
        body = resp.json()
        assert "samples" in body
        assert "saved" in body
        assert isinstance(body["samples"], list)
        assert len(body["samples"]) > 0
        assert body["saved"] == []


class TestWorkflowCRUD:
    def test_save_workflow_returns_id(self, client: TestClient):
        workflow = {
            "name": "Test Workflow",
            "description": "A workflow for testing",
            "nodes": [],
            "edges": [],
        }
        resp = client.put("/api/workflows", json=workflow)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "id" in body

    def test_get_saved_workflow(self, client: TestClient):
        workflow = {
            "id": "test-wf-1",
            "name": "Test Workflow",
            "description": "A workflow for testing",
            "nodes": [],
            "edges": [],
        }
        client.put("/api/workflows", json=workflow)

        resp = client.get("/api/workflows/test-wf-1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "test-wf-1"
        assert body["name"] == "Test Workflow"

    def test_get_nonexistent_workflow(self, client: TestClient):
        resp = client.get("/api/workflows/does-not-exist")
        assert resp.status_code == 404

    def test_delete_workflow(self, client: TestClient):
        workflow = {
            "id": "test-wf-del",
            "name": "To Delete",
            "nodes": [],
            "edges": [],
        }
        client.put("/api/workflows", json=workflow)

        resp = client.delete("/api/workflows/test-wf-del")
        assert resp.status_code == 204

        # Verify it's gone from the saved list
        resp = client.get("/api/workflows")
        saved_ids = [w["id"] for w in resp.json()["saved"]]
        assert "test-wf-del" not in saved_ids

    def test_get_sample_workflow(self, client: TestClient):
        """Sample workflows should also be retrievable by ID."""
        resp = client.get("/api/workflows/simple-chat")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "simple-chat"
        assert body["name"] == "Simple Chat"
