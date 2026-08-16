"""Machine-readable operation policy derived from binary HWP FileHeader flags."""

from __future__ import annotations

from typing import cast

from .hwp_types import HwpCapability, HwpOperation, HwpRequiredTool

FLAG_NAMES = {
    0: "compressed",
    1: "password_protected",
    2: "distribution_document",
    3: "script",
    4: "drm",
    5: "xml_template_storage",
    6: "document_history",
    7: "digital_signature",
    8: "certificate_encrypted",
    9: "signature_reserve",
    10: "certificate_drm",
    11: "ccl",
    12: "mobile_optimized",
    13: "personal_information_security",
    14: "change_tracking",
    15: "public_license",
    16: "video_control",
    17: "toc_field_control",
}
OPERATIONS: tuple[HwpOperation, ...] = (
    "inspect",
    "read",
    "extract",
    "convert",
    "edit",
    "create",
    "render",
)
INSPECTOR_PROVENANCE = {
    "name": "birkin-bounded-hwp-fileheader",
    "implementation": "internal-stdlib-read-only",
    "provenance": "birkin.office.hwp_cfb+hwp_security_gate",
    "executes_content": False,
    "decrypts_content": False,
}


def tool(name: str) -> HwpRequiredTool:
    return HwpRequiredTool(name=name)


def protected_reason(flags: int) -> tuple[str, str, HwpRequiredTool] | None:
    if flags & (1 << 2):
        return (
            "hwp_distribution_document_refused",
            "distribution HWP body streams are not plain text and no approved distribution decryptor is registered",
            tool("approved-binary-hwp-distribution-decryptor"),
        )
    if flags & (1 << 1):
        return (
            "hwp_password_decryptor_unavailable",
            "password-protected HWP requires an exact user credential and an approved decryptor; neither flow is registered",
            tool("approved-binary-hwp-password-decryptor+credential-flow"),
        )
    if flags & ((1 << 4) | (1 << 10)):
        return (
            "hwp_drm_document_refused",
            "DRM-protected HWP requires an approved entitlement-aware decryptor that is not registered",
            tool("approved-binary-hwp-drm-decryptor+entitlement-flow"),
        )
    if flags & (1 << 8):
        return (
            "hwp_certificate_decryptor_unavailable",
            "certificate-encrypted HWP requires an approved certificate credential flow that is not registered",
            tool("approved-binary-hwp-certificate-decryptor+credential-flow"),
        )
    return None


def capabilities(flags: int, evidence: tuple[str, ...]) -> dict[str, dict[str, object]]:
    result = {
        "inspect": HwpCapability(
            "inspect",
            "available",
            "hwp_header_inspection_available",
            "bounded CFB identity and FileHeader flag inspection is available without content execution",
            evidence,
            None,
        ).to_dict()
    }
    protected = protected_reason(flags)
    for raw_operation in ("read", "extract", "convert", "edit", "render"):
        operation = cast("HwpOperation", raw_operation)
        if protected is not None:
            code, reason, required = protected
            capability = HwpCapability(
                operation, "refused", code, reason, evidence, required
            )
        else:
            capability = HwpCapability(
                operation,
                "unavailable",
                "hwp_approved_engine_unavailable",
                "no provenance-approved binary HWP content engine is registered",
                evidence,
                tool("approved-binary-hwp-content-engine"),
            )
        result[raw_operation] = capability.to_dict()
    result["create"] = HwpCapability(
        "create",
        "unavailable",
        "hwp_approved_writer_unavailable",
        "no provenance-approved binary HWP writer is registered",
        (),
        tool("approved-binary-hwp-writer"),
    ).to_dict()
    return result


def unsupported_reasons(flags: int) -> list[str]:
    reasons: list[str] = []
    for bit, reason in (
        (2, "hwp_distribution_document_refused"),
        (1, "hwp_password_decryptor_unavailable"),
        (4, "hwp_drm_document_refused"),
        (10, "hwp_drm_document_refused"),
        (8, "hwp_certificate_decryptor_unavailable"),
    ):
        if flags & (1 << bit) and reason not in reasons:
            reasons.append(reason)
    return reasons


def flag_evidence(flags: int) -> tuple[tuple[str, ...], dict[str, object]]:
    present = tuple(name for bit, name in FLAG_NAMES.items() if flags & (1 << bit))
    evidence: dict[str, object] = {
        "raw_flags": flags,
        "flags_present": list(present),
        "unknown_flag_mask": flags & ~sum(1 << bit for bit in FLAG_NAMES),
    }
    evidence.update(
        {name: bool(flags & (1 << bit)) for bit, name in FLAG_NAMES.items()}
    )
    return present, evidence
