"""Tests for profile API routes."""

import io
import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from birkin.gateway.app import create_app
from birkin.gateway.deps import get_wiki_memory, reset_wiki_memory, set_wiki_memory
from birkin.gateway.routers.profile import reset_import_manager
from birkin.memory.wiki import WikiMemory

app = create_app()


@pytest.fixture(autouse=True)
def _clean_deps():
    tmpdir = tempfile.mkdtemp()
    wiki = WikiMemory(root=tmpdir)
    wiki.init()
    set_wiki_memory(wiki)
    reset_import_manager()
    yield
    reset_wiki_memory()
    reset_import_manager()


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


def _chatgpt_fixture() -> bytes:
    data = [
        {
            "id": "conv-001",
            "title": "Test Chat",
            "create_time": 1700000000.0,
            "current_node": "n2",
            "mapping": {
                "n1": {
                    "id": "n1",
                    "parent": None,
                    "message": {
                        "author": {"role": "user"},
                        "content": {"parts": ["I'm a backend developer working on Birkin"]},
                        "create_time": 1700000001.0,
                        "metadata": {},
                    },
                },
                "n2": {
                    "id": "n2",
                    "parent": "n1",
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {"parts": ["That's great!"]},
                        "create_time": 1700000002.0,
                        "metadata": {},
                    },
                },
            },
        }
    ]
    return json.dumps(data).encode()


def _claude_fixture() -> bytes:
    data = [
        {
            "uuid": "conv-uuid-001",
            "name": "Python Chat",
            "created_at": "2024-06-15T10:00:00Z",
            "chat_messages": [
                {"uuid": "m1", "text": "Help me with Python", "sender": "human", "created_at": "2024-06-15T10:00:00Z"},
                {"uuid": "m2", "text": "Sure!", "sender": "assistant", "created_at": "2024-06-15T10:00:01Z"},
            ],
        }
    ]
    return json.dumps(data).encode()


class TestImportEndpoint:
    def test_upload_non_json_rejected(self, client):
        resp = client.post(
            "/api/profile/import",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 400
        assert "json" in resp.json()["detail"].lower()

    def test_upload_invalid_json_rejected(self, client):
        resp = client.post(
            "/api/profile/import",
            files={"file": ("test.json", b"not json", "application/json")},
        )
        assert resp.status_code == 400

    def test_upload_unknown_format_rejected(self, client):
        data = json.dumps([{"unknown": "format"}]).encode()
        resp = client.post(
            "/api/profile/import",
            files={"file": ("export.json", data, "application/json")},
        )
        assert resp.status_code == 400
        assert "Unrecognized" in resp.json()["detail"]

    def test_upload_chatgpt_starts_job(self, client):
        resp = client.post(
            "/api/profile/import",
            files={"file": ("conversations.json", _chatgpt_fixture(), "application/json")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "started"
        assert body["conversations_found"] == 1
        assert body["source_format"] == "chatgpt"
        assert "job_id" in body

    def test_upload_claude_starts_job(self, client):
        resp = client.post(
            "/api/profile/import",
            files={"file": ("claude.json", _claude_fixture(), "application/json")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source_format"] == "claude"


class TestJobStatusEndpoint:
    def test_nonexistent_job(self, client):
        resp = client.get("/api/profile/import/nonexistent")
        assert resp.status_code == 404

    def test_job_status_after_upload(self, client):
        upload = client.post(
            "/api/profile/import",
            files={"file": ("conversations.json", _chatgpt_fixture(), "application/json")},
        )
        job_id = upload.json()["job_id"]

        resp = client.get(f"/api/profile/import/{job_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == job_id
        assert body["conversations_found"] == 1


class TestProfileReadEndpoint:
    def test_empty_profile(self, client):
        resp = client.get("/api/profile")
        assert resp.status_code == 200
        body = resp.json()
        assert body["exists"] is False

    def test_profile_with_data(self, client):
        wiki = get_wiki_memory()
        wiki.ingest("entities", "user-profile", "# User Profile\n\n**Role:** Backend Developer\n")
        wiki.ingest("concepts", "user-expertise", "# User Expertise\n\n- Python\n- FastAPI\n")
        wiki.ingest("concepts", "user-interests", "# User Interests\n\n- AI\n- DevOps\n")

        resp = client.get("/api/profile")
        assert resp.status_code == 200
        body = resp.json()
        assert body["exists"] is True
        assert body["job_role"] == "Backend Developer"
        assert "Python" in body["expertise_areas"]
        assert "AI" in body["interests"]


class TestProfileDeleteEndpoint:
    def test_delete_empty(self, client):
        resp = client.delete("/api/profile")
        assert resp.status_code == 200
        assert resp.json()["pages_deleted"] == "0"

    def test_delete_existing(self, client):
        wiki = get_wiki_memory()
        wiki.ingest("entities", "user-profile", "# User Profile\n\n**Role:** Dev\n")
        wiki.ingest("concepts", "user-expertise", "# Expertise\n\n- Go\n")

        resp = client.delete("/api/profile")
        assert resp.status_code == 200
        assert int(resp.json()["pages_deleted"]) >= 2

        # Verify deleted
        resp2 = client.get("/api/profile")
        assert resp2.json()["exists"] is False


class TestUserProfileFromWiki:
    def test_from_wiki_empty(self):
        tmpdir = tempfile.mkdtemp()
        wiki = WikiMemory(root=tmpdir)
        wiki.init()

        from birkin.core.context.profile import UserProfile

        profile = UserProfile.from_wiki(wiki)
        assert profile.is_empty

    def test_from_wiki_populated(self):
        tmpdir = tempfile.mkdtemp()
        wiki = WikiMemory(root=tmpdir)
        wiki.init()
        wiki.ingest("entities", "user-profile", "# User Profile\n\n**Role:** Data Scientist\n")
        wiki.ingest("concepts", "user-expertise", "# Expertise\n\n- ML\n- Python\n")
        wiki.ingest("concepts", "user-interests", "# Interests\n\n- LLMs\n")
        wiki.ingest(
            "concepts",
            "user-style",
            "# Communication Style\n\nConcise and data-driven\n\n## Tools & Technologies\n\n- Jupyter\n- PyTorch\n",
        )

        from birkin.core.context.profile import UserProfile

        profile = UserProfile.from_wiki(wiki)
        assert not profile.is_empty
        assert profile.job_role == "Data Scientist"
        assert "ML" in profile.expertise_areas
        assert "LLMs" in profile.interests
        assert profile.communication_style == "Concise and data-driven"
        assert "Jupyter" in profile.preferred_tools

    def test_to_prompt_section_with_new_fields(self):
        from birkin.core.context.profile import UserProfile

        profile = UserProfile(
            job_role="Engineer",
            expertise_areas=["Python", "Go"],
            interests=["AI"],
            preferred_tools=["VSCode"],
        )
        section = profile.to_prompt_section()
        assert "Engineer" in section
        assert "Python" in section
        assert "AI" in section
        assert "VSCode" in section
