from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import pytest

from birkin.browser_aside_control import BrowserControlAuthority
from birkin.computer_use.capability_types import (
    DisplayServer,
    PermissionState,
    PlatformProbe,
)
from birkin.native.product_surface_authorities import (
    BrowserAsideProjectionSource as CanonicalBrowserAsideProjectionSource,
)
from birkin.native.product_surfaces import (
    BrowserAsideProjectionSource,
    BrowserSurfaceAuthority,
    ComputerUseSurfaceAuthority,
    NativeProductSurfaceAuthority,
    OfficeSurfaceAuthority,
)
from birkin.office.errors import DocumentError
from birkin.office.service import DocumentService


def test_browser_aside_projection_source_import_is_compatible() -> None:
    assert BrowserAsideProjectionSource is CanonicalBrowserAsideProjectionSource


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _objects(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    return [_object(item) for item in cast(list[object], value)]


def _product(tmp_path: Path) -> NativeProductSurfaceAuthority:
    now = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
    return NativeProductSurfaceAuthority(
        browser=BrowserSurfaceAuthority.for_testing(
            workspace_id="session-1",
            status={
                "live": True,
                "browser_generation": 7,
                "browser_revision": 3,
                "frame_revision": 2,
                "display_url": "http://127.0.0.1:8123/",
                "frame_ref": "frame:7:2",
                "frame_digest": "safe-digest",
            },
            control=BrowserControlAuthority(lambda: now.timestamp()),
            now=lambda: now,
        ),
        computer_use=ComputerUseSurfaceAuthority(
            probe=PlatformProbe(
                platform="darwin",
                display_server=DisplayServer.QUARTZ,
                interactive=True,
                accessibility=PermissionState.NOT_DETERMINED,
                screen_capture=PermissionState.GRANTED,
                responsible_process="Birkin",
            ),
            now=lambda: now,
        ),
        office=OfficeSurfaceAuthority(DocumentService(tmp_path / "office")),
    )


def test_surface_revisions_gap_and_seeded_secret_redaction(tmp_path: Path) -> None:
    product = _product(tmp_path)
    secret = "sk-seeded_PHASE10_SECRET_123456789"
    product.browser.set_test_refusal(f"authorization=Bearer {secret}")

    first = product.snapshots({"browser_aside": 0, "computer_use": 0, "office": 0})
    assert [item.surface for item in first] == ["browser_aside", "computer_use", "office"]
    assert all(item.revision == 1 for item in first)
    encoded = json.dumps([item.payload for item in first], sort_keys=True).encode()
    assert secret.encode() not in encoded
    assert b"Bearer" not in encoded

    assert product.snapshots({"browser_aside": 1}) == ()
    product.browser.set_test_refusal("network_refused")
    recovered = product.snapshots({"browser_aside": 0})
    assert len(recovered) == 1
    assert recovered[0].revision == 2
    assert recovered[0].full_snapshot is True
    assert recovered[0].reset_reason == "revision_gap"


def test_browser_projection_has_private_generation_lease_frame_and_navigation(
    tmp_path: Path,
) -> None:
    product = _product(tmp_path)
    product.browser.acquire("macos:main", "human")
    payload = product.snapshots({"browser_aside": 0})[0].payload
    assert payload["profile"] == {"kind": "private_workspace", "generation": 7}
    control = _object(payload["control"])
    assert control["owner_kind"] == "human"
    assert control["epoch"] == 1
    assert payload["frame"] == {"ref": "frame:7:2", "revision": 2}
    assert _object(payload["navigation"])["display_url"] == "http://127.0.0.1:8123/"
    assert "profile_path" not in json.dumps(payload)


def test_browser_command_refuses_personal_profile_path(tmp_path: Path) -> None:
    product = _product(tmp_path)
    handler = product.handlers(lambda _kind, _payload: None)["browser.start"]
    with pytest.raises(ValueError, match="private workspace profile"):
        _ = handler({
            "profile_path": str(
                Path.home() / "Library/Application Support/Google/Chrome"
            )
        })


def test_computer_use_never_prompts_and_projects_bound_one_shot_expiry(
    tmp_path: Path,
) -> None:
    product = _product(tmp_path)
    computer = product.computer_use
    expires = datetime(2026, 8, 20, 12, 1, tzinfo=timezone.utc)
    computer.record_consent(
        grant_id="cu_grant_projection_123456",
        state="approved",
        action="click",
        application_ref="app:7",
        window_ref="window:9",
        prior_receipt="receipt:before",
        expires_at=expires,
    )
    computer.record_receipt("receipt:after", verdict="confirmed")

    payload = product.snapshots({"computer_use": 0})[0].payload
    status = _object(payload["status"])
    consent = _object(payload["consent"])
    assert status["permission_prompted"] is False
    assert status["permissions"] == {
        "accessibility": "not_determined",
        "screen_capture": "granted",
    }
    assert consent["one_shot"] is True
    assert consent["application_ref"] == "app:7"
    assert consent["window_ref"] == "window:9"
    assert consent["expires_at"] == expires.isoformat()
    assert payload["receipts"] == [{"receipt_ref": "receipt:after", "verdict": "confirmed"}]


def test_office_projection_create_and_secure_open_stay_in_service_jail(
    tmp_path: Path,
) -> None:
    product = _product(tmp_path)
    handlers = product.handlers(lambda _kind, _payload: None)
    created = handlers["office.create"]({
        "format": "docx",
        "content": {"paragraphs": ["Phase 10"]},
        "output_name": "phase-10.docx",
    })
    artifact = _object(created["document"])
    opened = handlers["office.open"]({"artifact": artifact})
    payload = product.snapshots({"office": 0})[0].payload
    opened_document = _object(opened["document"])
    source = _object(opened_document["source"])
    documents = _objects(payload["documents"])
    receipts = _objects(payload["receipts"])

    assert Path(cast(str, artifact["uri"])).is_relative_to(product.office.service.home)
    assert source["sha256"] == artifact["content_hash"]
    assert payload["inventory"]
    assert documents[0]["artifact_id"] == artifact["artifact_id"]
    assert [item["operation"] for item in receipts] == [
        "document_create", "document_open"
    ]
    with pytest.raises(DocumentError):
        _ = handlers["office.open"]({
            "artifact": {
                **artifact,
                "uri": str(tmp_path.parent / "outside.docx"),
            }
        })
    assert _object(product.office.snapshot()["refusal"])["code"] == "path_refused"
