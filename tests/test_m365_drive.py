from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import zipfile
import urllib.error
import urllib.request
from email.message import Message
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from birkin import config, store
from birkin.m365_drive import import_document, resolve_source
from birkin.m365_graph import GraphClient, GraphError, GraphUncertainError
from birkin.office.search import search_sources
from birkin.office.service import DocumentService
from birkin.tools import build_registry
from birkin.tools._types import ToolContext


def _xlsx() -> bytes:
    from io import BytesIO

    target = BytesIO()
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>')
        archive.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>quarterly revenue</t></is></c></row></sheetData></worksheet>')
    return target.getvalue()


class FakeGraph:
    def __init__(self, payload: bytes, *, etag: str = '"v1"', denied: bool = False, metadata_id: str = "item-1"):
        self.payload = payload
        self.etag = etag
        self.denied = denied
        self.metadata_id = metadata_id

    def request(self, method: str, path: str, body: object = None) -> dict[str, Any]:
        if path.startswith("/me?"):
            return {"id": "account-a", "userPrincipalName": "a@example.com", "mail": "a@example.com"}
        if path == "/organization?$select=id":
            return {"value": [{"id": "tenant-a"}]}
        if self.denied:
            raise GraphError("forbidden")
        return {"id": self.metadata_id, "name": "report.xlsx", "eTag": self.etag, "size": len(self.payload), "file": {}}

    def download(self, path: str, *, max_bytes: int) -> bytes:
        assert path == "/me/drive/items/item-1/content"
        assert len(self.payload) <= max_bytes
        return self.payload


@pytest.fixture
def connected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DocumentService:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path / "home"))
    config.clear_birkin_home_cache()
    store._write_json(config.connections_path(), {
        "microsoft-365": {
            "account_id": "account-a", "account_name": "a@example.com",
            "generation": "generation-a", "secret_env": "TEST_GRAPH_TOKEN",
            "scopes": ["Files.Read", "User.Read"], "revoked": False,
            "verified_identity": {"id": "account-a", "name": "a@example.com", "generation": "generation-a", "tenant_id": "tenant-a"},
        }
    })
    monkeypatch.setenv("TEST_GRAPH_TOKEN", "token")
    return DocumentService(tmp_path / "home" / "office")


def test_authenticated_import_binds_remote_identity_and_search_freshness(connected: DocumentService) -> None:
    graph = FakeGraph(_xlsx())
    imported = import_document("item-1", client=graph, service=connected)
    provenance = imported["provenance"]

    result = search_sources(
        "revenue", [{"scope": "allowed_connection", "import_id": provenance["import_id"]}],
        extract=connected.extract_document,
        resolve_connected=lambda source: resolve_source(source, client=graph),
    )

    assert result["excluded_sources"] == 0
    assert result["results"][0]["version_status"] == "verified_remote"
    assert result["results"][0]["is_older_version"] is False


def test_fresh_import_uses_identity_verification_client(
    connected: DocumentService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = store._read_json(config.connections_path(), {})
    records["microsoft-365"]["verified_identity"] = None
    store._write_json(config.connections_path(), records)
    graph = FakeGraph(_xlsx())
    observed: list[bool] = []
    monkeypatch.setattr(
        "birkin.m365_drive.graph_client",
        lambda *, allow_unverified=False: observed.append(allow_unverified) or graph,
    )

    imported = import_document("item-1", service=connected)

    assert observed == [True]
    assert imported["provenance"]["tenant_id"] == "tenant-a"


def test_remote_version_change_is_reported_stale(connected: DocumentService) -> None:
    imported = import_document("item-1", client=FakeGraph(_xlsx()), service=connected)
    graph = FakeGraph(_xlsx(), etag='"v2"')
    resolved = resolve_source({"import_id": imported["provenance"]["import_id"]}, client=graph)
    assert resolved["version"] == '"v1"'
    assert resolved["current_version"] == '"v2"'


def test_revoked_or_switched_account_is_excluded(connected: DocumentService) -> None:
    imported = import_document("item-1", client=FakeGraph(_xlsx()), service=connected)
    source = {"scope": "allowed_connection", "import_id": imported["provenance"]["import_id"]}
    denied = search_sources("revenue", [source], extract=connected.extract_document, resolve_connected=lambda value: resolve_source(value, client=FakeGraph(_xlsx(), denied=True)))
    assert denied["excluded_sources"] == 1

    records = store._read_json(config.connections_path(), {})
    records["microsoft-365"]["account_id"] = "account-b"
    records["microsoft-365"]["account_name"] = "b@example.com"
    records["microsoft-365"]["generation"] = "generation-b"
    store._write_json(config.connections_path(), records)
    switched = search_sources("revenue", [source], extract=connected.extract_document, resolve_connected=lambda value: resolve_source(value, client=FakeGraph(_xlsx())))
    assert switched["excluded_sources"] == 1


def test_caller_cannot_pair_import_with_another_artifact(connected: DocumentService) -> None:
    imported = import_document("item-1", client=FakeGraph(_xlsx()), service=connected)
    source = {
        "import_id": imported["provenance"]["import_id"],
        "artifact": {"uri": "C:/attacker.xlsx", "content_hash": "0" * 64},
    }
    with pytest.raises(ValueError, match="일치하지 않습니다"):
        resolve_source(source, client=FakeGraph(_xlsx()))


def test_graph_download_does_not_forward_bearer_token_to_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[urllib.request.Request] = []

    class Response(BytesIO):
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    class Opener:
        def open(self, request: urllib.request.Request, *, timeout: float) -> Response:
            requests.append(request)
            if len(requests) == 1:
                headers = Message()
                headers["Location"] = "https://download.example.test/item"
                raise urllib.error.HTTPError(request.full_url, 302, "Found", headers, None)
            return Response(b"content")

    monkeypatch.setattr("birkin.m365_graph.open_no_redirect", Opener().open)
    assert GraphClient("secret").download("/me/drive/items/item/content", max_bytes=20) == b"content"
    assert requests[0].get_header("Authorization") == "Bearer secret"
    assert requests[1].get_header("Authorization") is None


def test_graph_request_never_forwards_bearer_token_to_another_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin_authorization: list[str | None] = []
    target_authorization: list[str | None] = []

    class TargetHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def do_GET(self) -> None:
            target_authorization.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

    target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)

    class OriginHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def do_GET(self) -> None:
            origin_authorization.append(self.headers.get("Authorization"))
            self.send_response(302)
            self.send_header(
                "Location",
                f"http://127.0.0.1:{target.server_port}/target",
            )
            self.send_header("Content-Length", "0")
            self.end_headers()

    origin = ThreadingHTTPServer(("127.0.0.1", 0), OriginHandler)
    threads = [
        threading.Thread(target=target.serve_forever),
        threading.Thread(target=origin.serve_forever),
    ]
    for thread in threads:
        thread.start()
    monkeypatch.setattr(
        "birkin.m365_graph.ORIGIN", f"http://127.0.0.1:{origin.server_port}"
    )
    try:
        with pytest.raises(GraphError, match="HTTP 302"):
            GraphClient("secret").request("GET", "/redirect")
    finally:
        origin.shutdown()
        target.shutdown()
        origin.server_close()
        target.server_close()
        for thread in threads:
            thread.join(2)
            assert not thread.is_alive()

    assert origin_authorization == ["Bearer secret"]
    assert target_authorization == []


def test_graph_download_records_origin_network_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    health: list[str | None] = []

    class Opener:
        def open(self, request: urllib.request.Request, *, timeout: float) -> None:
            raise urllib.error.URLError("offline")

    monkeypatch.setattr("birkin.m365_graph.open_no_redirect", Opener().open)
    monkeypatch.setattr("birkin.m365_graph.record_sync_result", health.append)
    with pytest.raises(GraphUncertainError, match="응답"):
        GraphClient("secret", track_health=True).download("/me/drive/items/item/content", max_bytes=20)
    assert health == ["temporarily_unavailable"]


def test_graph_download_records_cdn_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    health: list[str | None] = []
    calls = 0

    class Opener:
        def open(self, request: urllib.request.Request, *, timeout: float) -> None:
            nonlocal calls
            calls += 1
            headers = Message()
            if calls == 1:
                headers["Location"] = "https://download.example.test/item"
                raise urllib.error.HTTPError(request.full_url, 302, "Found", headers, None)
            raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", headers, None)

    monkeypatch.setattr("birkin.m365_graph.open_no_redirect", Opener().open)
    monkeypatch.setattr("birkin.m365_graph.record_sync_result", health.append)
    with pytest.raises(GraphError, match="503"):
        GraphClient("secret", track_health=True).download("/me/drive/items/item/content", max_bytes=20)
    assert health == ["http_503"]


def test_graph_download_records_read_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    health: list[str | None] = []

    class BrokenResponse:
        def read(self, size: int) -> bytes:
            raise OSError("connection reset")

        def close(self) -> None:
            pass

    class Opener:
        def open(self, request: urllib.request.Request, *, timeout: float) -> BrokenResponse:
            return BrokenResponse()

    monkeypatch.setattr("birkin.m365_graph.open_no_redirect", Opener().open)
    monkeypatch.setattr("birkin.m365_graph.record_sync_result", health.append)
    with pytest.raises(GraphUncertainError, match="읽지 못했습니다"):
        GraphClient("secret", track_health=True).download("/me/drive/items/item/content", max_bytes=20)
    assert health == ["temporarily_unavailable"]


def test_import_rejects_empty_etag(connected: DocumentService) -> None:
    with pytest.raises(GraphError, match="올바르지 않습니다"):
        import_document("item-1", client=FakeGraph(_xlsx(), etag=""), service=connected)


def test_import_rejects_mismatched_item_identity(connected: DocumentService) -> None:
    with pytest.raises(GraphError, match="올바르지 않습니다"):
        import_document("item-1", client=FakeGraph(_xlsx(), metadata_id="other"), service=connected)


def test_registered_import_tool_uses_authenticated_graph_path(
    connected: DocumentService, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    graph = FakeGraph(_xlsx())
    monkeypatch.setattr("birkin.m365_drive.graph_client", lambda **_: graph)
    registry = build_registry(ToolContext(cfg={}, client=None, cwd=tmp_path), include={"documents"})

    result = registry.execute("m365_document_import", {"drive_item_id": "item-1"})

    assert not result.is_error
    body = json.loads(str(result.content))
    assert body["provenance"]["drive_item_id"] == "item-1"
    assert Path(body["artifact"]["uri"]).is_file()
