from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Protocol, cast, final

from birkin import approvals, store
from birkin.browser_aside_control import BrowserControlAuthority
from birkin.browser_aside_errors import BrowserAsideError
from birkin.browser_aside_service import BrowserAsideService
from birkin.browser_aside_store import MAX_FRAME_BYTES
from birkin.computer_use.capability_types import PlatformProbe
from birkin.computer_use.doctor import doctor_report
from birkin.office.errors import DocumentError
from birkin.office.job_runner import DocumentServiceRunner
from birkin.office.service import DocumentService

MAX_OFFICE_SNAPSHOT_ITEMS: Final = 8


class BrowserAsideProjectionSource(Protocol):
    def status(self) -> dict[str, object]: ...
    def start(self, *, actor_id: str = ..., control_epoch: int = ...) -> tuple[dict[str, object], bool]: ...
    def navigate(self, url: str, *, expected_generation: int, expected_revision: int) -> dict[str, object]: ...
    def close(self) -> dict[str, object]: ...


def _exact(payload: Mapping[str, object], keys: set[str], operation: str) -> None:
    if set(payload) != keys:
        raise ValueError(f"{operation} payload does not match the canonical contract")


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    unknown = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in unknown):
        raise ValueError(f"{label} must be an object")
    return cast(dict[str, object], unknown)


@final
class BrowserSurfaceAuthority:
    def __init__(self, service: BrowserAsideProjectionSource, control: BrowserControlAuthority, *, now: Callable[[], datetime] | None = None) -> None:
        self._service, self._control = service, control
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._test_status: dict[str, object] | None = None
        self._refusal: str | None = None
        self._history: list[str] = []
        self._history_index = -1
        self._loading = False

    @classmethod
    def for_testing(cls, *, workspace_id: str, status: dict[str, object], control: BrowserControlAuthority, now: Callable[[], datetime]) -> BrowserSurfaceAuthority:
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
        frame_ref, digest = status.get("frame_ref"), status.get("frame_digest")
        return {
            "profile": {"kind": "private_workspace", "generation": status.get("browser_generation", 0)},
            "runtime": {"live": status.get("live", False), "engine": status.get("engine", "chromium"), "revision": status.get("browser_revision", 0)},
            "control": {"owner_kind": lease.owner_kind if lease else "none", "epoch": lease.epoch if lease else 0, "expires_at": datetime.fromtimestamp(lease.expires_at, timezone.utc).isoformat() if lease else None},
            "navigation": {"display_url": status.get("display_url", ""), "loading": self._loading, "history": {"can_go_back": self._history_index > 0, "can_go_forward": 0 <= self._history_index < len(self._history) - 1, "entries": list(self._history), "index": self._history_index}},
            "frame": {"ref": frame_ref, "revision": status.get("frame_revision", 0), "digest": digest, "media_type": "image/png" if frame_ref and digest else None, "max_bytes": MAX_FRAME_BYTES},
            "refusal": self._refusal,
        }

    def _identity(self, payload: dict[str, object], operation: str) -> tuple[int, int]:
        _exact(payload, {"generation", "revision"}, operation)
        generation, revision = payload["generation"], payload["revision"]
        if isinstance(generation, bool) or not isinstance(generation, int) or isinstance(revision, bool) or not isinstance(revision, int):
            raise ValueError("browser navigation identity is invalid")
        return generation, revision

    def _navigate(self, url: str, generation: int, revision: int) -> dict[str, object]:
        self._loading = True
        try:
            result = self._service.navigate(url, expected_generation=generation, expected_revision=revision)
        except BrowserAsideError as exc:
            self._refusal = exc.code
            raise
        finally:
            self._loading = False
        self._refusal = None
        return result

    def start(self, payload: dict[str, object]) -> dict[str, object]:
        if "profile_path" in payload or "profile" in payload:
            raise ValueError("Browser Aside only permits its private workspace profile")
        _exact(payload, set(), "browser.start")
        status, created = self._service.start(actor_id="human:macos")
        return {"created": created, "status": status}

    def navigate(self, payload: dict[str, object]) -> dict[str, object]:
        _exact(payload, {"url", "generation", "revision"}, "browser.navigate")
        url = payload["url"]
        if not isinstance(url, str) or not url.strip():
            raise ValueError("browser navigation address is invalid")
        generation, revision = payload["generation"], payload["revision"]
        if isinstance(generation, bool) or not isinstance(generation, int) or isinstance(revision, bool) or not isinstance(revision, int):
            raise ValueError("browser navigation identity is invalid")
        previous = dict(self._test_status or self._service.status()).get("display_url")
        if not self._history and isinstance(previous, str) and previous:
            self._history.append(previous)
            self._history_index = 0
        result = self._navigate(url, generation, revision)
        del self._history[self._history_index + 1:]
        self._history.append(cast(str, result.get("display_url", url)))
        self._history = self._history[-32:]
        self._history_index = len(self._history) - 1
        return result

    def history(self, payload: dict[str, object], *, delta: int) -> dict[str, object]:
        generation, revision = self._identity(payload, "browser.history")
        target = self._history_index + delta
        if target < 0 or target >= len(self._history):
            raise ValueError("browser history target is unavailable")
        result = self._navigate(self._history[target], generation, revision)
        self._history_index = target
        return result

    def reload(self, payload: dict[str, object]) -> dict[str, object]:
        generation, revision = self._identity(payload, "browser.reload")
        if self._history_index < 0:
            raise ValueError("browser reload target is unavailable")
        return self._navigate(self._history[self._history_index], generation, revision)

    def close(self, payload: dict[str, object] | None = None) -> dict[str, object]:
        _exact(payload or {}, set(), "browser.close")
        result = self._service.close()
        self._history, self._history_index, self._refusal = [], -1, None
        return result


@final
class ComputerUseSurfaceAuthority:
    def __init__(self, *, probe: PlatformProbe, now: Callable[[], datetime] | None = None) -> None:
        self._status = doctor_report(probe)
        capabilities = cast(dict[str, dict[str, object]], self._status["capabilities"])
        available = any(item["state"] != "unsupported" for item in capabilities.values())
        self._status["backend"] = {"state": "available" if available else "unavailable", "display_server": probe.display_server.value}
        self._status["binding"] = {"state": "bound" if probe.responsible_process else "unbound", "responsible_process": probe.responsible_process}
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._consent: dict[str, object] | None = None
        self._receipts: list[dict[str, object]] = []

    def record_consent(self, *, grant_id: str, state: str, action: str, application_ref: str, window_ref: str, prior_receipt: str, expires_at: datetime) -> None:
        if not grant_id.startswith("cu_grant_") or state not in {"proposed", "approved", "rejected", "expired", "consumed"}:
            raise ValueError("Computer Use grant identity or state is invalid")
        if expires_at.tzinfo is None:
            raise ValueError("Computer Use consent expiry must be timezone-aware")
        self._consent = {"grant_id": grant_id, "state": state, "action": action, "application_ref": application_ref, "window_ref": window_ref, "prior_receipt": prior_receipt, "expires_at": expires_at.isoformat(), "one_shot": True}

    def record_receipt(self, receipt_ref: str, *, verdict: str) -> None:
        self._receipts.append({"receipt_ref": receipt_ref, "verdict": verdict})
        self._receipts = self._receipts[-MAX_OFFICE_SNAPSHOT_ITEMS:]

    def _current(self, grant_id: object) -> dict[str, object]:
        consent = self._consent
        if consent is None or not isinstance(grant_id, str) or consent["grant_id"] != grant_id:
            raise ValueError("Computer Use grant_id does not match the active grant")
        expiry = datetime.fromisoformat(cast(str, consent["expires_at"]))
        if self._now() >= expiry and consent["state"] in {"proposed", "approved"}:
            consent["state"] = "expired"
            self._receipts.append({"grant_id": grant_id, "operation": "grant_expiry", "verdict": "expired"})
        return consent

    def answer(self, payload: dict[str, object]) -> dict[str, object]:
        _exact(payload, {"grant_id", "decision"}, "computer.answer")
        consent = self._current(payload["grant_id"])
        if consent["state"] != "proposed" or payload["decision"] not in {"approve", "reject"}:
            raise ValueError("Computer Use grant cannot accept this answer")
        consent["state"] = "approved" if payload["decision"] == "approve" else "rejected"
        receipt = {"grant_id": consent["grant_id"], "operation": "consent_answer", "verdict": consent["state"]}
        self._receipts.append(receipt)
        return {"consent": dict(consent), "receipt": receipt}

    def execute(self, payload: dict[str, object]) -> dict[str, object]:
        _exact(payload, {"grant_id", "application_ref", "window_ref"}, "computer.execute")
        consent = self._current(payload["grant_id"])
        if consent["state"] == "consumed":
            raise ValueError("Computer Use grant was already consumed")
        if consent["state"] != "approved":
            raise ValueError("Computer Use grant is not approved")
        preserved = payload["application_ref"] == consent["application_ref"] and payload["window_ref"] == consent["window_ref"]
        if not preserved:
            raise ValueError("Computer Use foreground focus binding changed")
        consent["state"] = "consumed"
        receipt = {"grant_id": consent["grant_id"], "operation": "execute_once", "verdict": "executed", "focus_preserved": True, "application_ref": consent["application_ref"], "window_ref": consent["window_ref"]}
        self._receipts.append(receipt)
        return {"consent": dict(consent), "receipt": receipt}

    def snapshot(self) -> dict[str, object]:
        if self._consent is not None:
            _ = self._current(self._consent["grant_id"])
        return {"status": self._status, "consent": dict(self._consent) if self._consent else None, "receipts": list(self._receipts[-MAX_OFFICE_SNAPSHOT_ITEMS:])}


@final
class OfficeSurfaceAuthority:
    def __init__(self, service: DocumentService) -> None:
        self.service = service
        self._documents: dict[str, dict[str, object]] = {}
        self._diffs: dict[str, dict[str, object]] = {}
        self._request_commands: dict[str, str] = {}
        self._receipts: list[Mapping[str, object]] = []
        self._refusal: dict[str, object] | None = None
        self._form: dict[str, object] = {"format": "docx", "output_name": "", "content": {"paragraphs": []}}
        self._selected: str | None = None

    def snapshot(self) -> dict[str, object]:
        return {"inventory": self.service.adapter_inventory(), "form": dict(self._form), "selected_artifact_id": self._selected, "documents": list(self._documents.values()), "diffs": list(self._diffs.values()), "receipts": list(self._receipts), "refusal": self._refusal}

    def _retain(self, artifact_id: str, document: dict[str, object], receipt: Mapping[str, object]) -> None:
        if artifact_id not in self._documents and len(self._documents) == MAX_OFFICE_SNAPSHOT_ITEMS:
            del self._documents[next(iter(self._documents))]
        self._documents[artifact_id] = document
        self._receipts.append(receipt)
        self._receipts = self._receipts[-MAX_OFFICE_SNAPSHOT_ITEMS:]
        self._selected, self._refusal = artifact_id, None

    def _refused(self, exc: DocumentError) -> None:
        code = exc.code.value.lower()
        if code in {"permission_denied", "policy_denied", "source_changed"}:
            code = "path_refused"
        self._refusal = {"code": code, "message": exc.message}

    def register_import(
        self,
        reference: Mapping[str, object],
        source: Path,
    ) -> dict[str, object]:
        expected = reference.get("sha256")
        jail_name = reference.get("jail_name")
        if not isinstance(expected, str) or not isinstance(jail_name, str):
            raise ValueError("Office import reference is invalid")
        try:
            result = self.service.import_document(
                source,
                expected_sha256=expected,
                output_name=jail_name,
            )
        except DocumentError as exc:
            self._refused(exc)
            raise
        artifact = dict(cast(Mapping[str, object], result["artifact"]))
        receipt = dict(cast(Mapping[str, object], result["receipt"]))
        artifact_id = cast(str, artifact["artifact_id"])
        self._retain(
            artifact_id,
            {
                **artifact,
                "provenance": {
                    "operation": "document_import",
                    "import_id": reference.get("import_id"),
                    "content_hash": artifact["content_hash"],
                },
                "conversion": None,
                "active_content": [],
            },
            receipt,
        )
        return {"artifact": artifact, "receipt": receipt}

    def _document(self, artifact_id: object) -> dict[str, object]:
        if not isinstance(artifact_id, str) or artifact_id not in self._documents:
            raise ValueError("Office artifact is not registered in this workspace")
        document = self._documents[artifact_id]
        return {
            key: document[key]
            for key in (
                "artifact_id",
                "content_hash",
                "media_type",
                "uri",
                "sensitivity",
                "acl_fingerprint",
            )
        }

    def compare(self, payload: dict[str, object]) -> dict[str, object]:
        _exact(
            payload,
            {"left_artifact_id", "right_artifact_id"},
            "office.compare",
        )
        left = self._document(payload["left_artifact_id"])
        right = self._document(payload["right_artifact_id"])
        diff = self.service.compare_documents(left, right)
        identity = json.dumps(
            {
                "left": left["content_hash"],
                "right": right["content_hash"],
                "version": diff["version"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        diff_id = f"diff-{hashlib.sha256(identity.encode()).hexdigest()[:32]}"
        projected = {"diff_id": diff_id, **diff}
        self._diffs[diff_id] = projected
        if len(self._diffs) > MAX_OFFICE_SNAPSHOT_ITEMS:
            del self._diffs[next(iter(self._diffs))]
        self._refusal = None
        return {"diff": projected}

    def draft(self, payload: dict[str, object]) -> dict[str, object]:
        _exact(
            payload,
            {"template_artifact_id", "diff_id", "output_name"},
            "office.draft",
        )
        template = self._document(payload["template_artifact_id"])
        diff_id, output_name = payload["diff_id"], payload["output_name"]
        if not isinstance(diff_id, str) or diff_id not in self._diffs:
            raise ValueError("Office diff is not registered in this workspace")
        if not isinstance(output_name, str) or not output_name:
            raise ValueError("Office output_name must be a non-empty string")
        identity = json.dumps(
            {
                "template": template["content_hash"],
                "diff_id": diff_id,
                "output_name": output_name,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        draft_id = f"draft-{hashlib.sha256(identity.encode()).hexdigest()[:32]}"
        rendered = self.service.render_comparison_draft(
            template,
            self._diffs[diff_id],
            draft_name=f"{draft_id}.docx",
        )
        draft_artifact = dict(cast(Mapping[str, object], rendered["artifact"]))
        record = store.add_pending(
            category="office",
            title="Save Office comparison report",
            description="Publish the Python-produced report draft after approval",
            payload={
                "draft_id": draft_id,
                "diff_id": diff_id,
                "draft_artifact": draft_artifact,
                "output_name": output_name,
            },
            origin="native-office",
        )
        approval_id = cast(str, record["id"])
        return {
            "draft_id": draft_id,
            "diff_id": diff_id,
            "approval": {
                "approval_id": approval_id,
                "status": "pending",
                "summary": record["title"],
            },
        }

    @staticmethod
    def approval_event(result: Mapping[str, object]) -> dict[str, object]:
        approval = cast(Mapping[str, object], result["approval"])
        return {
            "approval_id": approval["approval_id"],
            "summary": approval["summary"],
            "description": "Publish the Python-produced report draft after approval",
            "category": "office",
            "status": "pending",
            "risk": "medium",
            "sealed": True,
            "decided": False,
            "draft_id": result["draft_id"],
            "diff_id": result["diff_id"],
        }

    def bind_request_command(self, approval_id: str, command_id: str) -> None:
        self._request_commands[approval_id] = command_id

    def answers(self, approval_id: str) -> bool:
        record = store.get_pending(approval_id)
        return record is not None and record.get("category") == "office"

    def answer(self, approval_id: str, decision: str, reason: str) -> dict[str, object]:
        record = store.get_pending(approval_id)
        if record is None or record.get("category") != "office":
            raise ValueError("Office approval is unavailable")
        payload = cast(dict[str, object], record.get("payload"))
        draft_id, diff_id = payload.get("draft_id"), payload.get("diff_id")
        if decision == "reject":
            result = approvals.reject(approval_id, reason=reason)
            if not result.get("ok"):
                return {"outcome": "answered_elsewhere", "approval_id": approval_id}
            return {
                "outcome": "rejected",
                "approval_id": approval_id,
                "draft_id": draft_id,
                "diff_id": diff_id,
            }
        if decision != "approve":
            raise ValueError("decision must be approve or reject")
        claimed = approvals.claim(approval_id)
        if not claimed.get("ok"):
            return {"outcome": "answered_elsewhere", "approval_id": approval_id}
        try:
            draft_artifact = _mapping(
                payload.get("draft_artifact"),
                "Office rendered draft",
            )
            output_name = payload.get("output_name")
            if not isinstance(output_name, str):
                raise ValueError("Office approval output_name is invalid")
            validation = dict(self.service.validate_artifact(draft_artifact))
            if validation.get("valid") is not True:
                raise ValueError("sealed Office draft failed structural validation")
            publication = DocumentServiceRunner(self.service).publish(
                artifact=draft_artifact,
                output_name=output_name,
            )
            artifact = dict(cast(Mapping[str, object], publication["artifact"]))
        except Exception:
            _ = store.resolve_pending(
                approval_id,
                "error",
                updates={"failure_stage": "office_save"},
            )
            raise
        receipt_ref = f"office-save:{artifact['artifact_id']}"
        _ = store.resolve_pending(
            approval_id,
            "approved",
            updates={"action_receipt": receipt_ref},
        )
        artifact_id = cast(str, artifact["artifact_id"])
        self._retain(
            artifact_id,
            {
                **artifact,
                "provenance": {
                    "operation": "office_approved_save",
                    "approval_id": approval_id,
                    "draft_id": draft_id,
                    "diff_id": diff_id,
                },
                "conversion": None,
                "active_content": [],
            },
            {
                "operation": "office_approved_save",
                "receipt_ref": receipt_ref,
                "approval_id": approval_id,
                "artifact_id": artifact_id,
            },
        )
        return {
            "outcome": "approved",
            "approval_id": approval_id,
            "draft_id": draft_id,
            "diff_id": diff_id,
            "request_command_id": self._request_commands.get(approval_id, ""),
            "artifact": artifact,
            "validation": validation,
            "receipt_ref": receipt_ref,
        }

    def create(self, payload: dict[str, object]) -> dict[str, object]:
        _exact(payload, {"format", "content", "output_name"}, "office.create")
        format_name, output_name = payload["format"], payload["output_name"]
        if not isinstance(format_name, str) or not isinstance(output_name, str):
            raise ValueError("Office format and output_name must be strings")
        content = _mapping(payload["content"], "Office content")
        self._form = {"format": format_name, "output_name": output_name, "content": content}
        try:
            result = self.service.create_document(format=format_name, content=content, output_name=output_name)
        except DocumentError as exc:
            self._refused(exc)
            raise
        artifact, receipt = dict(result["draft_artifact"]), dict(result["receipt"])
        artifact_id = cast(str, artifact["artifact_id"])
        self._retain(artifact_id, {**artifact, "provenance": {"operation": "document_create", "content_hash": artifact["content_hash"]}, "conversion": None, "active_content": []}, receipt)
        return {"document": artifact, "receipt": receipt}

    def select(self, payload: dict[str, object]) -> dict[str, object]:
        _exact(payload, {"artifact_id"}, "office.select")
        artifact_id = payload["artifact_id"]
        if not isinstance(artifact_id, str) or artifact_id not in self._documents:
            raise ValueError("Office document selection is unavailable")
        self._selected = artifact_id
        return {"selected_artifact_id": artifact_id}

    def open(self, payload: dict[str, object]) -> dict[str, object]:
        _exact(payload, {"artifact"}, "office.open")
        artifact = _mapping(payload["artifact"], "Office artifact")
        try:
            inspection = self.service.inspect_document(artifact)
        except DocumentError as exc:
            self._refused(exc)
            raise
        source, metadata = cast(dict[str, object], inspection["source"]), cast(dict[str, object], inspection["metadata"])
        risks = cast(dict[str, object], inspection["risks"])
        digest = cast(str, source["sha256"])
        receipt = {"operation": "document_open", "source_sha256": digest}
        self._retain(cast(str, artifact.get("artifact_id", digest)), {"artifact_id": artifact.get("artifact_id", digest), "content_hash": digest, "media_type": metadata["media_type"], "uri": artifact["uri"], "sensitivity": artifact.get("sensitivity", "unknown"), "acl_fingerprint": artifact.get("acl_fingerprint", ""), "provenance": {"operation": "document_open", "content_hash": digest, "adapter": inspection["adapter"]}, "conversion": None, "active_content": risks["active_content"]}, receipt)
        return {"document": inspection, "receipt": receipt}

    def convert(self, payload: dict[str, object]) -> dict[str, object]:
        _exact(payload, {"artifact", "target_format", "output_name", "loss_budget"}, "office.convert")
        artifact = _mapping(payload["artifact"], "Office artifact")
        target, name = payload["target_format"], payload["output_name"]
        if not isinstance(target, str) or not isinstance(name, str):
            raise ValueError("Office conversion format and output_name must be strings")
        budget = _mapping(payload["loss_budget"], "Office loss budget")
        try:
            result = self.service.convert_document(artifact, target_format=target, output_name=name, loss_budget=budget)
        except DocumentError as exc:
            self._refused(exc)
            raise
        draft, receipt = dict(result["draft_artifact"]), dict(result["receipt"])
        artifact_id = cast(str, draft["artifact_id"])
        self._retain(artifact_id, {**draft, "provenance": {"operation": "document_convert", "source_sha256": result["source_sha256"]}, "conversion": receipt, "active_content": []}, receipt)
        return {"document": draft, "receipt": receipt}
