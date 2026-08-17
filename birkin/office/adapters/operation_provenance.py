"""Built-in operation contracts used by the authoritative adapter catalog."""

from __future__ import annotations

from .approved_package_provenance import PYPDF, PYTHON_HWPX
from .base import IntegrationMode, OperationState
from .provenance_models import OperationRecord

SECURITY_LIMIT = (
    "Untrusted input is bounded by package preflight; semantic XML is not a sandbox."
)
_FIDELITY = "Only the named narrow operation is covered; no arbitrary layout rewrite is implied."


def _operation(
    state: OperationState,
    reason: str,
    *,
    availability: str = "built-in",
    mode: IntegrationMode = IntegrationMode.INTERNAL_STDLIB,
    install_probe: str | None = None,
    refusal_reason: str | None = None,
    security: str = SECURITY_LIMIT,
    fidelity: str = _FIDELITY,
) -> OperationRecord:
    return OperationRecord(
        state,
        availability,
        reason,
        mode,
        security,
        fidelity,
        install_probe,
        refusal_reason,
    )


def _unsupported(reason: str, refusal: str) -> OperationRecord:
    return _operation(
        OperationState.UNSUPPORTED,
        reason,
        availability="unavailable",
        mode=IntegrationMode.NONE,
        refusal_reason=refusal,
    )


def _compare() -> OperationRecord:
    return _operation(
        OperationState.READ_ONLY,
        "Internal layered byte, semantic-text, and ZIP-package comparison.",
        availability="layered",
        fidelity=(
            "Semantic comparison is bounded and normalized; package comparison is unavailable "
            "for PDF, and visual equality is never claimed."
        ),
    )


def _render() -> OperationRecord:
    return _operation(
        OperationState.READ_ONLY,
        "Internal bounded extraction provides a deterministic structured preview.",
        availability="structured-preview-only",
        refusal_reason="PDF, PNG, and thumbnail requests return RENDER_UNAVAILABLE.",
        fidelity=(
            "A structured preview is semantic extraction, not a visual render or visual proof."
        ),
    )


def _validate() -> OperationRecord:
    return _operation(
        OperationState.READ_ONLY,
        "Internal layered package, schema-root, security, and openability checks.",
        fidelity=(
            "Validation is partial and reports unrun layers; it is not visual fidelity, trust, "
            "accessibility, or full standards conformance."
        ),
    )


def _convert(*, pdf: bool = False) -> OperationRecord:
    return _operation(
        OperationState.CONVERSION_ONLY,
        "Deterministic UTF-8 TXT conversion uses bounded extraction and a required loss budget.",
        availability="conditional" if pdf else "built-in",
        mode=IntegrationMode.OPTIONAL_PYTHON if pdf else IntegrationMode.INTERNAL_STDLIB,
        install_probe=PYPDF.install_probe if pdf else None,
        fidelity="Text projection is intentionally lossy and never a native Office conversion.",
    )


def opc_operations(create_probe: str) -> tuple[tuple[str, OperationRecord], ...]:
    return (
        ("inspect", _operation(OperationState.NATIVE, "Internal ZIP/XML structural inspection.")),
        (
            "extract",
            _operation(
                OperationState.READ_ONLY,
                "Internal bounded semantic text extraction for the package format.",
                fidelity="Only the supported text reading order and locators are extracted.",
            ),
        ),
        (
            "create",
            _operation(
                OperationState.NATIVE,
                "Text-first creation is wired through an approved lazy Python backend.",
                availability="conditional",
                mode=IntegrationMode.OPTIONAL_PYTHON,
                install_probe=create_probe,
            ),
        ),
        ("compare", _compare()),
        (
            "fill",
            _operation(
                OperationState.LOSSLESS_SURGICAL,
                "Caller-supplied field descriptors and bindings produce a narrow edit plan.",
            ),
        ),
        (
            "patch",
            _operation(
                OperationState.LOSSLESS_SURGICAL,
                "One narrow existing target can be patched while untouched ZIP payloads are preserved.",
            ),
        ),
        ("render", _render()),
        ("validate", _validate()),
        ("convert", _convert()),
    )


PDF_OPERATIONS = (
    (
        "inspect",
        _operation(
            OperationState.READ_ONLY,
            "Approved optional pypdf from office-advanced provides read-only PDF state inspection.",
            availability="conditional",
            mode=IntegrationMode.OPTIONAL_PYTHON,
            install_probe=PYPDF.install_probe,
            fidelity="Identity, state, forms, signatures, and active content are inventoried; trust is not verified.",
        ),
    ),
    (
        "extract",
        _operation(
            OperationState.READ_ONLY,
            "Approved optional pypdf from office-advanced provides bounded page-text extraction.",
            availability="conditional",
            mode=IntegrationMode.OPTIONAL_PYTHON,
            install_probe=PYPDF.install_probe,
            fidelity="No OCR, visual ordering, or completeness claim is made.",
        ),
    ),
    (
        "create",
        _operation(
            OperationState.NATIVE,
            "Internal text-first PDF creation supports ASCII and refuses non-Latin text.",
            availability="bounded",
            fidelity=(
                "Output is text-first A4 with approximate wrapping; non-Latin output is "
                "unavailable because no approved backend is registered."
            ),
            refusal_reason="No approved non-Latin PDF creation backend is registered.",
        ),
    ),
    ("compare", _compare()),
    ("fill", _unsupported("PDF form filling is not implemented.", "No approved lossless PDF form implementation.")),
    ("patch", _unsupported("General PDF rewriting is refused.", "PDF object rewriting cannot meet the lossless-surgical contract.")),
    ("render", _render()),
    ("validate", _validate()),
    ("convert", _convert(pdf=True)),
)


def hwpx_operations() -> tuple[tuple[str, OperationRecord], ...]:
    return tuple(
        (name, operation)
        if name != "create"
        else (
            name,
            _operation(
                OperationState.NATIVE,
                "Exact-pinned python-hwpx provides local text-first blank authoring; "
                "trusted-template derivation remains copy-on-write.",
                availability="conditional",
                mode=IntegrationMode.OPTIONAL_PYTHON,
                install_probe=PYTHON_HWPX.install_probe,
                fidelity=(
                    "Blank authoring uses package defaults; template derivation "
                    "preserves unmatched package parts."
                ),
            ),
        )
        for name, operation in opc_operations("source-provenance-required")
    )
