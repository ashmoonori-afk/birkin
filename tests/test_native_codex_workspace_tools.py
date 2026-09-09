from __future__ import annotations

import json
from pathlib import Path
from typing import cast
import zipfile

from birkin import config, mcp_server, store
from birkin.codex_session import CodexAppServerSession
from birkin.native.product_surface_authorities import MAX_OFFICE_SNAPSHOT_ITEMS
from birkin.runtime import build_session
from birkin.workspace import runtime_adapter
from birkin.workspace.runtime_adapter import RuntimeWorkspaceAdapter
from birkin.tools import research


def _single_cell_xlsx(path: Path) -> Path:
    parts = {
        "[Content_Types].xml": b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>',
        "xl/workbook.xml": b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Revenue" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><v>7</v></c></row></sheetData></worksheet>',
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)
    return path


def test_native_runtime_scopes_codex_and_checkpoints_to_workspace(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(config, "load_config", lambda: {"provider": "codex-cli", "model": ""})
    captured = {}

    def build(cfg, **kwargs):
        captured.update(cfg)
        return object()

    monkeypatch.setattr(runtime_adapter, "build_session", build)
    adapter = RuntimeWorkspaceAdapter("native-test", lambda *_: None, workspace_root=workspace)

    assert adapter.runtime_session() is not None
    assert captured["workspace_root"] == str(workspace.resolve())
    assert captured["birkin_mcp"] is True and captured["birkin_mcp_scope"] == "workspace"
    assert captured["repl_warm_session"] is True


def test_native_runtime_omits_default_codex_model(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(
        config, "load_config",
        lambda: {"provider": "codex-cli", "model": "default"},
    )
    adapter = RuntimeWorkspaceAdapter(
        "native-default-model", lambda *_: None, workspace_root=workspace,
    )

    warm = adapter.runtime_session()._build_warm()

    assert isinstance(warm, CodexAppServerSession)
    assert warm.model is None
    assert not any(arg.startswith('model="') for arg in warm._build_argv())


def test_codex_workspace_session_exposes_only_bounded_request_tools(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    monkeypatch.chdir(workspace)
    monkeypatch.setenv("BIRKIN_MCP_SCOPE", "workspace")

    tools = mcp_server._build_tools()
    assert set(tools) == {
        "memory_search", "memory_get_note", "memory_related",
        "skills_list", "load_skill", "work_item_request",
        "research_run", "inspect_document", "office_job_request",
    }
    text, is_error = tools["work_item_request"]["handler"]({
        "action": "create", "title": "검증 보고서 확인", "assignee": "검증 담당",
        "due_date": "2050-01-01", "session_id": "native-test", "source": {"job_id": "job-1"},
    })
    queued = json.loads(text)
    pending = store.get_pending(queued["id"])
    assert is_error is False and pending is not None and pending["category"] == "work_item"
    assert pending["status"] == "pending" and pending["payload"]["title"] == "검증 보고서 확인"

    session = build_session({
        "provider": "codex-cli", "model": "", "workspace_root": str(workspace),
        "birkin_mcp": True, "birkin_mcp_scope": "workspace",
    })
    warm = session._build_warm()
    assert session.ctx.cwd == workspace.resolve()
    assert isinstance(warm, CodexAppServerSession)
    assert warm.cwd == str(workspace.resolve()) and warm.birkin_mcp_scope == "workspace"
    assert warm.approval_policy == "on-request"
    argv = " ".join(warm._build_argv())
    assert "BIRKIN_MCP_SCOPE" in argv and "BIRKIN_HOME" in argv and "PYTHONIOENCODING" in argv


def test_native_import_descriptor_reaches_mcp_inspect_and_pending(
    tmp_path: Path, monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    source = _single_cell_xlsx(tmp_path / "Revenue.xlsx")
    prompts: list[str] = []

    class Runtime:
        cfg = {}

        def ask(self, text, *, on_text, on_progress=None):
            del on_text, on_progress
            prompts.append(text)
            return "검토했습니다."

    monkeypatch.chdir(workspace)
    monkeypatch.setenv("BIRKIN_HOME", str(home))
    monkeypatch.setenv("BIRKIN_MCP_SCOPE", "workspace")
    monkeypatch.setattr(config, "load_config", lambda: dict(config.DEFAULT_CONFIG))
    monkeypatch.setattr(
        runtime_adapter, "build_session", lambda *_args, **_kwargs: Runtime())
    adapter = RuntimeWorkspaceAdapter(
        "native-office-import", lambda *_args: None, workspace_root=workspace)

    imported = adapter.handlers()["file.import"]({"source_path": str(source)})
    reference = cast(dict[str, object], imported["reference"])
    artifact = cast(dict[str, object], imported["artifact"])
    office_source = {
        key: artifact[key] for key in (
            "artifact_id", "content_hash", "media_type", "uri",
            "sensitivity", "acl_fingerprint",
        )
    }
    office_source["media_type"] = "application/octet-stream"
    adapter.surface_authority.office.open({"artifact": office_source})
    for index in range(MAX_OFFICE_SNAPSHOT_ITEMS):
        adapter.surface_authority.office._retain(
            f"eviction-{index}", {
                "artifact_id": f"eviction-{index}",
                "content_hash": f"{index:064x}",
                "media_type": "text/plain",
                "uri": str(home / f"eviction-{index}.txt"),
                "sensitivity": "internal",
                "acl_fingerprint": "test",
            }, {})
    assert all(document.get("artifact_id") != artifact["artifact_id"]
               for document in adapter.surface_authority.office.snapshot()["documents"])
    adapter.handlers()["chat.send"]({
        "text": "문서를 검토하고 변경을 제안해 줘",
        "attachments": [reference],
    })
    descriptor_line = next(
        line for line in prompts[0].splitlines()
        if line.startswith('{"display_name_untrusted"'))
    descriptor = json.loads(descriptor_line)["office_source"]

    assert descriptor == {
        **office_source,
        "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    assert str(source) not in prompts[0]
    tools = mcp_server._build_tools()
    inspected, inspect_error = tools["inspect_document"]["handler"]({
        "source": descriptor,
    })
    assert inspect_error is False
    assert json.loads(inspected)["source"]["sha256"] \
        == descriptor["content_hash"]

    queued, queue_error = tools["office_job_request"]["handler"]({
        "request": "Revenue A1 값을 8로 바꿔 주세요.",
        "source": descriptor,
        "outcome": "Revenue A1을 8로 변경",
        "operations": [{
            "locator": {"sheet": "Revenue", "cell": "A1"}, "value": 8,
        }],
        "destination": str(workspace / "Revenue-updated.xlsx"),
        "overwrite_approved": False,
    })
    queued_body = json.loads(queued)
    assert queue_error is False
    pending = store.get_pending(queued_body["id"])
    assert pending is not None
    assert pending["status"] == "pending" and pending["category"] == "office_job"


def test_workspace_mcp_research_returns_complete_long_partial_result(
    tmp_path: Path, monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("BIRKIN_MCP_SCOPE", "workspace")
    monkeypatch.setattr(config, "load_config", lambda: {
        "provider": "codex-cli", "model": "default",
    })

    class Script:
        roles = {}

    answer = "근거 있는 긴 답변\n" + "본문" * 2000
    captured = {}
    monkeypatch.setattr(research.moirai_cli, "resolve_script_path", lambda name: Path(name))
    monkeypatch.setattr(research, "load_script", lambda path: Script())

    def run(*args, **kwargs):
        captured.update(kwargs)
        return {"run_id": "native-research", "status": "completed", "result": {
            "completion": "partial", "answer": answer,
            "reasons": ["추가 원문 필요"],
            "verification_basis": "인용 실재는 코드 확인, 의미는 모델 감사",
        }}

    monkeypatch.setattr(research, "run_script", run)
    text, is_error = mcp_server._build_tools()["research_run"]["handler"]({
        "question": "실제 흐름 확인",
    })

    assert is_error is False
    assert answer in text and "조사 상태: 일부 완료" in text
    assert "추가 원문 필요" in text and "검증 기준:" in text
    assert captured["args"]["_workspace"] == str(workspace.resolve())


def test_codex_waits_for_workspace_tool_inventory_before_first_turn() -> None:
    session = CodexAppServerSession(birkin_mcp=True, birkin_mcp_scope="workspace")
    session._thread_id = "thread-1"
    calls = []

    def request(method, params, timeout):
        calls.append((method, params, timeout))
        return {"data": [{
            "name": "birkin", "runtimeStatus": "connected",
            "tools": {"work_item_request": {}},
        }]}

    session.request = request
    session._require_birkin_mcp_ready()

    assert calls[0][:2] == (
        "mcpServerStatus/list",
        {"detail": "toolsAndAuthOnly", "threadId": "thread-1"},
    )
    assert 0 < calls[0][2] <= session.startup_timeout


def test_codex_polls_while_workspace_mcp_is_starting(monkeypatch) -> None:
    session = CodexAppServerSession(
        birkin_mcp=True, birkin_mcp_scope="workspace",
    )
    session._thread_id = "thread-1"
    replies = iter([
        {"data": [{"name": "birkin", "runtimeStatus": "starting"}]},
        {"data": [{
            "name": "birkin", "runtimeStatus": "connected",
            "tools": {"work_item_request": {}},
        }]},
    ])
    calls = []

    def request(method, params, timeout):
        calls.append((method, params, timeout))
        return next(replies)

    session.request = request
    monkeypatch.setattr("birkin.codex_session.time.sleep", lambda _: None)

    session._require_birkin_mcp_ready()

    assert len(calls) == 2
