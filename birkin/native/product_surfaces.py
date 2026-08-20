"""Python-owned projections for Browser Aside, Computer Use, and Office."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast, final

from birkin.browser_aside_control import BrowserControlAuthority
from birkin.browser_aside_service import BrowserAsideService
from birkin.computer_use.capability_types import PlatformProbe
from birkin.computer_use.doctor import doctor_report
from birkin.native.projection import public_native_mapping
from birkin.office.errors import DocumentError
from birkin.office.service import DocumentService

SurfaceEventSink = Callable[[str, dict[str, object]], object]
SurfaceHandler = Callable[[dict[str, object]], dict[str, object]]


def _exact(payload: Mapping[str, object], keys: set[str], operation: str) -> None:
    if set(payload) != keys:
        raise ValueError(f"{operation} payload does not match the canonical contract")


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    unknown = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in unknown):
        raise ValueError(f"{label} must be an object")
    return {cast(str, key): item for key, item in unknown.items()}


@final
class BrowserSurfaceAuthority:
    """Project and command the canonical private Browser Aside service."""

    def __init__(
        self,
        service: BrowserAsideService,
        control: BrowserControlAuthority,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._control = control
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._test_status: dict[str, object] | None = None
        self._refusal: str | None = None

    @classmethod
    def for_testing(
        cls,
        *,
        workspace_id: str,
        status: dict[str, object],
        control: BrowserControlAuthority,
        now: Callable[[], datetime],
    ) -> BrowserSurfaceAuthority:
        authority = cls(BrowserAsideService(workspace_id), control, now=now)
        authority._test_status = dict(status)
        return authority

    def acquire(self, actor_id: str, actor_kind: str) -> None:
        _ = self._control.acquire(actor_id, actor_kind)

    def set_test_refusal(self, refusal: str | None) -> None:
        self._refusal = refusal

    def snapshot(self) -> dict[str, object]:
        status = dict(self._test_status or self._service.status())
        lease = self._control.current()
        generation = status.get("browser_generation", 0)
        frame_revision = status.get("frame_revision", 0)
        return {
            "profile": {"kind": "private_workspace", "generation": generation},
            "runtime": {
                "live": status.get("live", False),
                "engine": status.get("engine", "chromium"),
                "revision": status.get("browser_revision", 0),
            },
            "control": {
                "owner_kind": lease.owner_kind if lease else "none",
                "epoch": lease.epoch if lease else 0,
                "expires_at": (
                    datetime.fromtimestamp(lease.expires_at, timezone.utc).isoformat()
                    if lease else None
                ),
            },
            "navigation": {"display_url": status.get("display_url", "")},
            "frame": {
                "ref": status.get("frame_ref"),
                "revision": frame_revision,
            },
            "refusal": self._refusal,
        }

    def start(self, payload: dict[str, object]) -> dict[str, object]:
        if "profile_path" in payload or "profile" in payload:
            raise ValueError("Browser Aside only permits its private workspace profile")
        _exact(payload, set(), "browser.start")
        status, created = self._service.start(actor_id="human:macos")
        return {"created": created, "status": status}

    def navigate(self, payload: dict[str, object]) -> dict[str, object]:
        _exact(payload, {"url", "generation", "revision"}, "browser.navigate")
        url, generation, revision = payload["url"], payload["generation"], payload["revision"]
        if not isinstance(url, str) or not isinstance(generation, int) or not isinstance(revision, int):
            raise ValueError("browser navigation identity is invalid")
        return self._service.navigate(
            url, expected_generation=generation, expected_revision=revision
        )


@final
class ComputerUseSurfaceAuthority:
    """Project never-prompt capabilities and exact one-shot consent state."""

    def __init__(
        self,
        *,
        probe: PlatformProbe,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._status = doctor_report(probe)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._consent: dict[str, object] | None = None
        self._receipts: list[dict[str, object]] = []

    def record_consent(
        self,
        *,
        grant_id: str,
        state: str,
        action: str,
        application_ref: str,
        window_ref: str,
        prior_receipt: str,
        expires_at: datetime,
    ) -> None:
        if expires_at.tzinfo is None:
            raise ValueError("Computer Use consent expiry must be timezone-aware")
        self._consent = {
            "grant_id": grant_id,
            "state": state,
            "action": action,
            "application_ref": application_ref,
            "window_ref": window_ref,
            "prior_receipt": prior_receipt,
            "expires_at": expires_at.isoformat(),
            "one_shot": True,
        }

    def record_receipt(self, receipt_ref: str, *, verdict: str) -> None:
        self._receipts.append({"receipt_ref": receipt_ref, "verdict": verdict})

    def snapshot(self) -> dict[str, object]:
        consent = dict(self._consent) if self._consent is not None else None
        if consent is not None:
            expiry = datetime.fromisoformat(cast(str, consent["expires_at"]))
            if self._now() >= expiry and consent["state"] in {"proposed", "approved"}:
                consent["state"] = "expired"
        return {
            "status": self._status,
            "consent": consent,
            "receipts": list(self._receipts),
        }


@final
class OfficeSurfaceAuthority:
    """Delegate document operations to DocumentService and project its results."""

    def __init__(self, service: DocumentService) -> None:
        self.service = service
        self._documents: dict[str, dict[str, object]] = {}
        self._receipts: list[dict[str, object]] = []
        self._refusal: dict[str, object] | None = None

    def snapshot(self) -> dict[str, object]:
        return {
            "inventory": self.service.adapter_inventory(),
            "documents": list(self._documents.values()),
            "receipts": list(self._receipts),
            "refusal": self._refusal,
        }

    def create(self, payload: dict[str, object]) -> dict[str, object]:
        _exact(payload, {"format", "content", "output_name"}, "office.create")
        format_name, output_name = payload["format"], payload["output_name"]
        if not isinstance(format_name, str) or not isinstance(output_name, str):
            raise ValueError("Office format and output_name must be strings")
        content = _mapping(payload["content"], "Office content")
        result = self.service.create_document(
            format=format_name, content=content, output_name=output_name
        )
        artifact = dict(result["draft_artifact"])
        self._documents[cast(str, artifact["artifact_id"])] = artifact
        receipt = dict(result["receipt"])
        self._receipts.append(receipt)
        self._refusal = None
        return {"document": artifact, "receipt": receipt}

    def open(self, payload: dict[str, object]) -> dict[str, object]:
        _exact(payload, {"artifact"}, "office.open")
        artifact = _mapping(payload["artifact"], "Office artifact")
        try:
            inspection = self.service.inspect_document(artifact)
        except DocumentError:
            self._refusal = {
                "code": "path_refused",
                "message": "Document path is outside the Office jail or changed.",
            }
            raise
        artifact_id = artifact.get("artifact_id")
        if isinstance(artifact_id, str):
            self._documents[artifact_id] = dict(artifact)
        receipt = {
            "operation": "document_open",
            "source_sha256": artifact.get("content_hash"),
        }
        self._receipts.append(receipt)
        self._refusal = None
        return {"document": inspection, "receipt": receipt}


@dataclass(frozen=True, slots=True)
class SurfaceSnapshot:
    surface: str
    revision: int
    payload: dict[str, object]
    full_snapshot: bool
    reset_reason: str


@final
class NativeProductSurfaceAuthority:
    """Revision and redact all product projections at the native boundary."""

    def __init__(
        self,
        *,
        browser: BrowserSurfaceAuthority,
        computer_use: ComputerUseSurfaceAuthority,
        office: OfficeSurfaceAuthority,
    ) -> None:
        self.browser = browser
        self.computer_use = computer_use
        self.office = office
        self._revisions = {name: 0 for name in self.surface_names}
        self._canonical: dict[str, str] = {}

    @property
    def surface_names(self) -> tuple[str, ...]:
        return ("browser_aside", "computer_use", "office")

    def _payload(self, surface: str) -> dict[str, object]:
        raw = {
            "browser_aside": self.browser.snapshot,
            "computer_use": self.computer_use.snapshot,
            "office": self.office.snapshot,
        }[surface]()
        public = public_native_mapping(raw)
        canonical = json.dumps(public, sort_keys=True, separators=(",", ":"))
        if self._canonical.get(surface) != canonical:
            self._canonical[surface] = canonical
            self._revisions[surface] += 1
        return public

    def snapshots(self, requested: Mapping[str, int]) -> tuple[SurfaceSnapshot, ...]:
        unknown = set(requested) - set(self.surface_names)
        if unknown:
            raise ValueError(f"unsupported native surfaces: {sorted(unknown)}")
        snapshots: list[SurfaceSnapshot] = []
        for surface in self.surface_names:
            if surface not in requested:
                continue
            known = requested[surface]
            if isinstance(known, bool) or known < 0:
                raise ValueError("surface revisions must be non-negative integers")
            payload = self._payload(surface)
            revision = self._revisions[surface]
            if known == revision:
                continue
            snapshots.append(SurfaceSnapshot(
                surface=surface,
                revision=revision,
                payload=payload,
                full_snapshot=True,
                reset_reason="initial" if known == 0 and revision == 1 else "revision_gap",
            ))
        return tuple(snapshots)

    def handlers(self, emit: SurfaceEventSink) -> dict[str, SurfaceHandler]:
        def wrapped(
            surface: str,
            event_type: str,
            operation: SurfaceHandler,
        ) -> SurfaceHandler:
            def handle(payload: dict[str, object]) -> dict[str, object]:
                result = operation(payload)
                _ = emit(event_type, {"surface": surface, "result": result})
                return result
            return handle

        return {
            "browser.start": wrapped("browser_aside", "browser.updated", self.browser.start),
            "browser.navigate": wrapped("browser_aside", "browser.updated", self.browser.navigate),
            "office.create": wrapped("office", "office.updated", self.office.create),
            "office.open": wrapped("office", "office.updated", self.office.open),
        }
