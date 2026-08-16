"""Machine-readable operation refusals for inspected PDF states."""

from __future__ import annotations

from .pdf_mutation import PDF_MUTATION_OPERATIONS, decide_pdf_mutation


def pdf_mutation_capabilities(
    form_type: str,
    content_type: str,
    *,
    encrypted: bool = False,
    credential_required: bool = False,
    signed: bool = False,
    doc_mdp: bool = False,
    multiple_revisions: bool = False,
) -> dict[str, dict[str, object]]:
    return {
        operation: dict(
            decide_pdf_mutation(
                operation,
                form_type=form_type,
                content_type=content_type,
                encrypted=encrypted,
                credential_required=credential_required,
                signed=signed,
                doc_mdp=doc_mdp,
                multiple_revisions=multiple_revisions,
            )
        )
        for operation in PDF_MUTATION_OPERATIONS
    }


def pdf_capabilities(
    form_type: str, content_type: str, extraction_reason: str | None
) -> dict[str, dict[str, object]]:
    if extraction_reason is not None:
        extract_state, extract_reason = "unavailable", extraction_reason
    elif form_type == "xfa":
        extract_state, extract_reason = "unavailable", "pdf_xfa_content_unsupported"
    elif content_type == "image_only":
        extract_state, extract_reason = "unavailable", "pdf_image_only_requires_ocr"
    else:
        extract_state, extract_reason = "read_only", "pdf_native_text_read_only"
    mutations = pdf_mutation_capabilities(
        form_type,
        content_type,
        encrypted=form_type == "unknown_encrypted",
        credential_required=form_type == "unknown_encrypted",
    )
    return {
        "inspect": {"state": "read_only", "reason": "pdf_inventory_only"},
        "extract": {"state": extract_state, "reason": extract_reason},
        **mutations,
        # Compatibility aliases remain refusals and identify the narrow class.
        "fill": dict(mutations["form_fill"]),
        "patch": dict(mutations["body_edit"]),
        "verify_signature": {
            "state": "unavailable",
            "reason": "pdf_cryptographic_signature_verification_unsupported",
        },
        "evaluate_signature_trust": {
            "state": "unavailable",
            "reason": "pdf_signature_trust_unsupported",
        },
    }
