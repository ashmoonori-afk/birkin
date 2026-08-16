"""Preflight and typed planning for trusted HWPX template derivation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .adapters.ooxml_surgery import (
    attribute_equals,
    element_blocks,
    splice_fragmented_text,
)
from .create_content import as_content, invalid_content
from .errors import DocumentError, DocumentErrorCode
from .package import preflight_package
from .package_types import ActiveContent


@dataclass(frozen=True)
class TemplateBinding:
    key: str
    value: str
    expected_text: str | None


@dataclass(frozen=True)
class HwpxTemplatePlan:
    bindings: tuple[TemplateBinding, ...]
    source_sha256: str
    warnings: tuple[str, ...]


def _consent(content: Mapping[str, object], key: str) -> bool:
    value = content.get(key, False)
    if not isinstance(value, bool):
        raise invalid_content(f"HWPX {key} must be a boolean")
    return value


def _bindings(value: object) -> tuple[TemplateBinding, ...]:
    if not isinstance(value, Mapping) or not value:
        raise invalid_content("HWPX bindings must be a non-empty object")
    raw = cast("Mapping[object, object]", value)
    if len(raw) > 10_000:
        raise invalid_content("HWPX bindings exceed the 10000 item limit")
    result: list[TemplateBinding] = []
    for raw_key, raw_value in raw.items():
        if not isinstance(raw_key, str) or not raw_key:
            raise invalid_content("HWPX binding keys must be non-empty strings")
        if isinstance(raw_value, str):
            result.append(TemplateBinding(raw_key, raw_value, None))
            continue
        binding = as_content(raw_value, f"HWPX binding {raw_key!r}")
        unknown = sorted(key for key in binding if key not in {"value", "expected_text"})
        if unknown:
            raise invalid_content(f"HWPX binding {raw_key!r} has unsupported keys: {unknown}")
        replacement = binding.get("value")
        expected = binding.get("expected_text")
        if not isinstance(replacement, str) or (expected is not None and not isinstance(expected, str)):
            raise invalid_content("HWPX binding value and expected_text must be strings")
        result.append(TemplateBinding(raw_key, replacement, expected))
    return tuple(result)


def _is_signature(name: str) -> bool:
    lowered = name.lower()
    return (
        "_xmlsignatures/" in lowered
        or "signature" in lowered.rsplit("/", 1)[-1]
        or lowered.endswith(".sigs")
    )


def _active_parts(names: list[str], scanned: list[ActiveContent]) -> list[str]:
    found = [item["part_uri"] for item in scanned]
    found.extend(
        name
        for name in names
        if re.search(r"(?:^|/)(?:scripts?|macros?)(?:/|$)", name, re.IGNORECASE)
    )
    return sorted(set(found))


def plan_hwpx_template(source: Path, content: Mapping[str, object]) -> HwpxTemplatePlan:
    allowed = {"bindings", "allow_active_content", "allow_signatures", "allow_external_relationships"}
    unknown = sorted(key for key in content if key not in allowed)
    if unknown:
        raise invalid_content(f"HWPX content has unsupported keys: {unknown}")
    bindings = _bindings(content.get("bindings"))
    manifest = preflight_package(source)
    names = list(manifest["parts"])
    active = _active_parts(names, manifest["active_content"])
    signatures = sorted(name for name in names if _is_signature(name))
    external = manifest["external_relationships"]
    warnings: list[str] = []
    risks = (
        (active, "allow_active_content", "active content"),
        (signatures, "allow_signatures", "signatures"),
        (external, "allow_external_relationships", "external relationships"),
    )
    for findings, consent_key, label in risks:
        if not findings:
            continue
        if not _consent(content, consent_key):
            raise DocumentError(
                DocumentErrorCode.POLICY_DENIED,
                "plan",
                f"HWPX template contains {label}; explicit {consent_key} consent is required",
                details={"risk": label, "findings": findings, "consent_field": consent_key},
            )
        warnings.append(f"template {label} preserved but never executed or trusted")
    for binding in bindings:
        matches: list[tuple[str, int, int]] = []
        for name, metadata in manifest["parts"].items():
            if re.fullmatch(r"Contents/section\d+\.xml", name) is None:
                continue
            xml = metadata["bytes"]
            for start, end, block in element_blocks(xml, b"hp:field"):
                if attribute_equals(block, b"hp:field", b"id", binding.key):
                    matches.append((name, start, end))
        if len(matches) != 1:
            raise DocumentError(
                DocumentErrorCode.AMBIGUOUS_LOCATOR,
                "plan",
                f"HWPX field id must match exactly once: {binding.key}",
                locator={"field": binding.key, "matches": len(matches)},
            )
        part, start, end = matches[0]
        _ = splice_fragmented_text(
            manifest["parts"][part]["bytes"],
            start,
            end,
            binding.value,
            expected_text=binding.expected_text,
        )
    return HwpxTemplatePlan(bindings, manifest["source_sha256"], tuple(warnings))
