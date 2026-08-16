"""Pure, machine-readable PDF mutation boundary decisions."""

from __future__ import annotations

from typing import Literal, TypedDict

PdfMutationOperation = Literal[
    "merge",
    "split",
    "rotate",
    "watermark",
    "form_fill",
    "encrypt",
    "decrypt",
    "ocr",
    "overlay",
    "annotation",
    "redaction",
    "metadata_edit",
    "lossy_reconstruction",
    "body_edit",
]

PDF_MUTATION_OPERATIONS: tuple[PdfMutationOperation, ...] = (
    "merge",
    "split",
    "rotate",
    "watermark",
    "form_fill",
    "encrypt",
    "decrypt",
    "ocr",
    "overlay",
    "annotation",
    "redaction",
    "metadata_edit",
    "lossy_reconstruction",
    "body_edit",
)


class PdfMutationDecision(TypedDict):
    operation: PdfMutationOperation
    state: Literal["unavailable"]
    reason: str
    mutation_class: str
    requires_copy_on_write: bool
    signature_effect: Literal["not_evaluated"]
    incremental_update_safety: Literal["unsupported"]
    loss_profile: str


_CLASSES: dict[PdfMutationOperation, str] = {
    "merge": "page_assembly",
    "split": "page_assembly",
    "rotate": "page_transform",
    "watermark": "overlay",
    "form_fill": "form_fill",
    "encrypt": "security",
    "decrypt": "security",
    "ocr": "lossy_reconstruction",
    "overlay": "overlay",
    "annotation": "annotation",
    "redaction": "redaction",
    "metadata_edit": "metadata_edit",
    "lossy_reconstruction": "lossy_reconstruction",
    "body_edit": "body_edit",
}

_BASE_REASONS: dict[PdfMutationOperation, str] = {
    "merge": "pdf_page_merge_unsupported",
    "split": "pdf_page_split_unsupported",
    "rotate": "pdf_page_rotation_unsupported",
    "watermark": "pdf_watermark_overlay_unsupported",
    "form_fill": "pdf_form_fill_unsupported",
    "encrypt": "pdf_encryption_write_unsupported",
    "decrypt": "pdf_decryption_write_unsupported",
    "ocr": "pdf_ocr_reconstruction_unsupported",
    "overlay": "pdf_overlay_unsupported",
    "annotation": "pdf_annotation_write_unsupported",
    "redaction": "pdf_redaction_unsupported",
    "metadata_edit": "pdf_metadata_edit_unsupported",
    "lossy_reconstruction": "pdf_lossy_reconstruction_unsupported",
    "body_edit": "pdf_native_body_edit_unsupported",
}


def parse_pdf_mutation_operation(value: object) -> PdfMutationOperation | None:
    if isinstance(value, str) and value in PDF_MUTATION_OPERATIONS:
        return value
    return None


def decide_pdf_mutation(
    operation: PdfMutationOperation,
    *,
    form_type: str,
    content_type: str,
    encrypted: bool,
    credential_required: bool,
    signed: bool,
    doc_mdp: bool,
    multiple_revisions: bool,
) -> PdfMutationDecision:
    """Return a refusal decision; this package intentionally has no PDF writer."""
    reason = _state_reason(
        operation,
        form_type=form_type,
        content_type=content_type,
        encrypted=encrypted,
        credential_required=credential_required,
        signed=signed,
        doc_mdp=doc_mdp,
        multiple_revisions=multiple_revisions,
    )
    lossy = operation in {"ocr", "lossy_reconstruction"} or (
        operation == "body_edit" and content_type == "image_only"
    )
    return {
        "operation": operation,
        "state": "unavailable",
        "reason": reason,
        "mutation_class": _CLASSES[operation],
        "requires_copy_on_write": True,
        "signature_effect": "not_evaluated",
        "incremental_update_safety": "unsupported",
        "loss_profile": "lossy_reconstruction_required" if lossy else "not_performed",
    }


def _state_reason(
    operation: PdfMutationOperation,
    *,
    form_type: str,
    content_type: str,
    encrypted: bool,
    credential_required: bool,
    signed: bool,
    doc_mdp: bool,
    multiple_revisions: bool,
) -> str:
    if credential_required:
        return "pdf_password_required"
    if doc_mdp:
        return "pdf_docmdp_mutation_unsupported"
    if signed:
        return "pdf_signed_mutation_unsupported"
    if multiple_revisions:
        return "pdf_incremental_revision_mutation_unsupported"
    if operation == "encrypt" and encrypted:
        return "pdf_already_encrypted"
    if operation == "decrypt" and not encrypted:
        return "pdf_not_encrypted"
    if encrypted:
        return (
            "pdf_decryption_write_unsupported"
            if operation == "decrypt"
            else "pdf_encrypted_mutation_unsupported"
        )
    if operation == "form_fill":
        return {
            "xfa": "pdf_xfa_unsupported",
            "acroform": "pdf_acroform_fill_unsupported",
        }.get(form_type, "pdf_no_interactive_form")
    if operation == "ocr" and content_type != "image_only":
        return "pdf_ocr_not_applicable"
    if operation == "body_edit":
        return {
            "image_only": "pdf_image_body_edit_requires_lossy_ocr",
            "empty_or_vector": "pdf_flat_body_edit_unsupported",
            "unknown_encrypted": "pdf_password_required",
        }.get(content_type, "pdf_native_body_edit_unsupported")
    return _BASE_REASONS[operation]
