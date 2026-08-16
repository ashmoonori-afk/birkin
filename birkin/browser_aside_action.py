"""Typed human/agent authority decisions for Browser Aside actions."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import final

from birkin import config
from birkin.browser_aside_egress import PolicyEgressGate
from birkin.browser_aside_errors import BrowserAsideError
from birkin.egress_scan import EgressScanError, inspect_payload

Fields = tuple[tuple[str, str], ...]


def _empty_receipt() -> dict[str, object]:
    return {}


@dataclass(frozen=True, slots=True)
class BrowserActionDecision:
    kind: str
    result: str
    code: str = ""
    approval: str = ""
    digest: str = ""
    receipt: Mapping[str, object] = field(default_factory=_empty_receipt)


@final
class BrowserActionAuthority:
    def __init__(
        self,
        *,
        egress: PolicyEgressGate,
        secrets_to_scan: tuple[str, ...],
        jail_root: str,
    ) -> None:
        self._egress = egress
        self._secrets = tuple(secret for secret in secrets_to_scan if secret)
        self._jail = Path(jail_root).resolve()
        self._approvals: dict[str, tuple[str, bool]] = {}

    def decide(
        self,
        *,
        kind: str,
        source: str,
        url: str = "",
        method: str = "GET",
        fields: Fields = (),
        path: str = "",
        gesture: str = "",
    ) -> BrowserActionDecision:
        if kind in {"clipboard", "permission"}:
            return self._deny(kind, "unsupported_capability")
        if kind == "popup":
            if source != "web_human" or not gesture:
                return self._deny("popup", "popup_blocked")
            return self._navigate(kind, source, url, gesture)
        if kind == "navigate":
            parsed_scheme = url.split(":", maxsplit=1)[0].lower()
            if parsed_scheme not in {"http", "https"}:
                return self._deny(
                    "external_protocol",
                    "external_protocol_denied",
                )
            return self._navigate("navigation", source, url, gesture)
        if kind == "form_submit":
            denied = self._egress_decision(kind, url)
            if denied is not None:
                return denied
            if self._contains_secret(fields):
                return self._deny(
                    kind,
                    "secret_scan_denied",
                    {"field_count": len(fields)},
                )
            if source == "web_human" and method == "GET" and gesture:
                return BrowserActionDecision(kind, "allow")
            return self._approval(kind, fields)
        if kind == "upload":
            target = Path(path).resolve()
            if (
                source != "web_human"
                or not gesture
                or not self._inside_jail(target)
            ):
                return self._deny(kind, "upload_jail_denied")
            denied = self._egress_decision(kind, url)
            return denied or self._approval(kind, (("path", str(target)),))
        if kind == "download_export":
            target = Path(path).resolve()
            if not self._inside_jail(target):
                return self._deny(kind, "export_jail_denied")
            return self._approval(kind, (("path", str(target)),))
        return self._deny(kind, "unsupported_action")

    def replay(
        self,
        approval: str,
        *,
        fields: Fields = (),
    ) -> BrowserActionDecision:
        stored = self._approvals.get(approval)
        digest = self._digest(fields)
        if stored is None or stored[1]:
            return self._deny("approval", "approval_stale")
        self._approvals[approval] = (stored[0], True)
        if not secrets.compare_digest(stored[0], digest):
            return self._deny("approval", "approval_stale")
        return BrowserActionDecision(
            "approval",
            "allow",
            digest=digest,
            receipt={"field_count": len(fields)},
        )

    def _navigate(
        self,
        kind: str,
        source: str,
        url: str,
        gesture: str,
    ) -> BrowserActionDecision:
        if self._contains_secret((("url", url),)):
            return self._deny(kind, "secret_detected")
        try:
            destination = self._egress.evaluate(url)
        except BrowserAsideError as exc:
            return self._deny(kind, exc.code)
        if source == "web_human" and gesture:
            return BrowserActionDecision(kind, "allow")
        if (
            destination.private
            or source in {"agent", "browser_page"}
        ):
            return self._approval(kind, (("url", destination.display_url),))
        return self._deny(kind, "gesture_required")

    def _egress_decision(
        self,
        kind: str,
        url: str,
    ) -> BrowserActionDecision | None:
        try:
            _ = self._egress.evaluate(url)
        except BrowserAsideError as exc:
            return self._deny(kind, exc.code)
        return None

    def _approval(
        self,
        kind: str,
        fields: Fields,
    ) -> BrowserActionDecision:
        digest = self._digest(fields)
        approval = secrets.token_urlsafe(18)
        self._approvals[approval] = (digest, False)
        return BrowserActionDecision(
            kind,
            "approval_required",
            approval=approval,
            digest=digest,
            receipt={"field_count": len(fields)},
        )

    @staticmethod
    def _deny(
        kind: str,
        code: str,
        receipt: Mapping[str, object] | None = None,
    ) -> BrowserActionDecision:
        return BrowserActionDecision(
            kind,
            "denied",
            code=code,
            receipt=receipt or {},
        )

    def _contains_secret(self, fields: Fields) -> bool:
        if any(
            secret and secret in value
            for _, value in fields
            for secret in self._secrets
        ):
            return True
        payload = dict(fields)
        try:
            inspect_payload(
                json.dumps(payload, ensure_ascii=False),
                payload,
                config.load_config(),
            )
        except EgressScanError:
            return True
        return False

    def _inside_jail(self, path: Path) -> bool:
        return path == self._jail or self._jail in path.parents

    @staticmethod
    def _digest(fields: Fields) -> str:
        payload = json.dumps(
            fields,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()
