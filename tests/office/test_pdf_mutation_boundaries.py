from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from birkin.office.adapters.pdf import PdfAdapter
from birkin.office.adapters.pdf_mutation import PDF_MUTATION_OPERATIONS
from birkin.office.adapters.pdf_types import mapping
from birkin.office.errors import DocumentError, DocumentErrorCode


def _pdf(objects: list[bytes]) -> bytes:
    data = bytearray(b"%PDF-1.7\n")
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    trailer = f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
    data.extend(f"{trailer}startxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def _base(
    *,
    catalog: bytes | None = None,
    page: bytes | None = None,
    extra: list[bytes] | None = None,
) -> bytes:
    content = b"BT /F1 12 Tf 72 720 Td (Hello PDF) Tj ET"
    default_page = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
    )
    stream = (
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
        + content + b"\nendstream"
    )
    return _pdf([
        catalog or b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        page or default_page,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        stream,
        *(extra or []),
    ])


def _image_pdf() -> bytes:
    drawing = b"q 1 0 0 1 0 0 cm /Im0 Do Q"
    page = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] "
        b"/Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>"
    )
    image = (
        b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 "
        b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Length 3 >>\n"
        b"stream\n000\nendstream"
    )
    stream = (
        b"<< /Length " + str(len(drawing)).encode() + b" >>\nstream\n"
        + drawing + b"\nendstream"
    )
    return _pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        page, image, stream,
    ])


def _form_pdf(*, xfa: bool = False) -> bytes:
    form = b"<< /Fields [7 0 R]" + (b" /XFA 8 0 R" if xfa else b"") + b" >>"
    widget = b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (name) >>"
    extra = [form, widget]
    if xfa:
        extra.append(b"<< /Length 6 >>\nstream\n<xfa/>\nendstream")
    catalog = b"<< /Type /Catalog /Pages 2 0 R /AcroForm 6 0 R >>"
    return _base(catalog=catalog, extra=extra)


def _signed_pdf() -> bytes:
    signature = (
        b"<< /Type /Sig /ByteRange [0 1 2 3] /Contents <01> "
        b"/Reference [<< /TransformMethod /DocMDP "
        b"/TransformParams << /P 1 >> >>] >>"
    )
    catalog = (
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 6 0 R "
        b"/Perms << /DocMDP 7 0 R >> >>"
    )
    extra = [b"<< /Fields [8 0 R] >>", signature, b"<< /FT /Sig /V 7 0 R >>"]
    return _base(catalog=catalog, extra=extra)


def _encrypted(data: bytes) -> bytes:
    output = BytesIO()
    writer = PdfWriter(clone_from=PdfReader(BytesIO(data), strict=True))
    writer.encrypt("correct horse", algorithm="RC4-128")
    _ = writer.write(output)
    return output.getvalue()


def _write(path: Path, data: bytes) -> Path:
    _ = path.write_bytes(data)
    return path


def _decision(adapter: PdfAdapter, path: Path, operation: str) -> dict[str, object]:
    return adapter.mutation_decision(path, operation)


def _blank_pdf() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    _ = writer.add_blank_page(width=100, height=100)
    _ = writer.write(output)
    return output.getvalue()


def _incremental_pdf(path: Path) -> Path:
    _ = path.write_bytes(_base())
    writer = PdfWriter(path, incremental=True)
    writer.add_metadata({"/Subject": "second revision"})
    _ = writer.write(path)
    return path


@pytest.mark.parametrize(
    ("operation", "mutation_class", "reason"),
    [
        ("merge", "page_assembly", "pdf_page_merge_unsupported"),
        ("split", "page_assembly", "pdf_page_split_unsupported"),
        ("rotate", "page_transform", "pdf_page_rotation_unsupported"),
        ("watermark", "overlay", "pdf_watermark_overlay_unsupported"),
        ("form_fill", "form_fill", "pdf_no_interactive_form"),
        ("encrypt", "security", "pdf_encryption_write_unsupported"),
        ("decrypt", "security", "pdf_not_encrypted"),
        ("ocr", "lossy_reconstruction", "pdf_ocr_not_applicable"),
        ("overlay", "overlay", "pdf_overlay_unsupported"),
        ("annotation", "annotation", "pdf_annotation_write_unsupported"),
        ("redaction", "redaction", "pdf_redaction_unsupported"),
        ("metadata_edit", "metadata_edit", "pdf_metadata_edit_unsupported"),
        (
            "lossy_reconstruction",
            "lossy_reconstruction",
            "pdf_lossy_reconstruction_unsupported",
        ),
        ("body_edit", "body_edit", "pdf_native_body_edit_unsupported"),
    ],
)
def test_native_pdf_exposes_narrow_unavailable_decisions(
    tmp_path: Path, operation: str, mutation_class: str, reason: str
) -> None:
    source = _write(tmp_path / "native.pdf", _base())
    decision = _decision(PdfAdapter(), source, operation)
    assert decision == {
        "operation": operation,
        "state": "unavailable",
        "reason": reason,
        "mutation_class": mutation_class,
        "requires_copy_on_write": True,
        "signature_effect": "not_evaluated",
        "incremental_update_safety": "unsupported",
        "loss_profile": (
            "lossy_reconstruction_required"
            if operation in {"ocr", "lossy_reconstruction"}
            else "not_performed"
        ),
    }


def test_content_and_form_states_produce_specific_refusals(tmp_path: Path) -> None:
    scan = _write(tmp_path / "scan.pdf", _image_pdf())
    flat = _write(tmp_path / "flat.pdf", _blank_pdf())
    acro = _write(tmp_path / "acro.pdf", _form_pdf())
    xfa = _write(tmp_path / "xfa.pdf", _form_pdf(xfa=True))

    assert _decision(PdfAdapter(), scan, "body_edit")["reason"] == (
        "pdf_image_body_edit_requires_lossy_ocr"
    )
    assert _decision(PdfAdapter(), scan, "ocr")["loss_profile"] == "lossy_reconstruction_required"
    assert _decision(PdfAdapter(), flat, "body_edit")["reason"] == (
        "pdf_flat_body_edit_unsupported"
    )
    assert _decision(PdfAdapter(), acro, "form_fill")["reason"] == (
        "pdf_acroform_fill_unsupported"
    )
    assert _decision(PdfAdapter(), xfa, "form_fill")["reason"] == (
        "pdf_xfa_unsupported"
    )


def test_security_and_revision_gates_precede_writer_claims(tmp_path: Path) -> None:
    locked = _write(tmp_path / "locked.pdf", _encrypted(_base()))
    signed = _write(tmp_path / "signed.pdf", _signed_pdf())
    incremental = _incremental_pdf(tmp_path / "incremental.pdf")

    assert all(
        _decision(PdfAdapter(), locked, operation)["reason"]
        == "pdf_password_required"
        for operation in PDF_MUTATION_OPERATIONS
    )
    unlocked = PdfAdapter(password="correct horse")
    assert _decision(unlocked, locked, "decrypt")["reason"] == (
        "pdf_decryption_write_unsupported"
    )
    assert _decision(PdfAdapter(), signed, "form_fill")["reason"] == (
        "pdf_docmdp_mutation_unsupported"
    )
    state = PdfAdapter().inspect(incremental)
    history = mapping(state["revision_history"])
    assert history is not None
    assert history.get("multiple_revisions_detected") is True
    assert _decision(PdfAdapter(), incremental, "rotate")["reason"] == (
        "pdf_incremental_revision_mutation_unsupported"
    )


def test_named_patch_refuses_without_writing_or_generic_reason(tmp_path: Path) -> None:
    source = _write(tmp_path / "scan.pdf", _image_pdf())
    before = source.read_bytes()
    before_hash = hashlib.sha256(before).hexdigest()

    with pytest.raises(DocumentError) as caught:
        _ = PdfAdapter().patch(source, {"type": "body_edit"})

    error = caught.value
    assert error.code is DocumentErrorCode.UNSUPPORTED_EDIT
    assert error.details["reason"] == "pdf_image_body_edit_requires_lossy_ocr"
    assert error.details["mutation_class"] == "body_edit"
    assert error.details["loss_profile"] == "lossy_reconstruction_required"
    assert source.read_bytes() == before
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before_hash
    assert list(tmp_path.iterdir()) == [source]


def test_unknown_operation_is_typed_and_does_not_open_the_pdf(tmp_path: Path) -> None:
    missing = tmp_path / "missing.pdf"
    with pytest.raises(DocumentError) as caught:
        _ = PdfAdapter().mutation_decision(missing, "replace_everything")
    assert caught.value.code is DocumentErrorCode.INVALID_INPUT
    assert caught.value.details["reason"] == "pdf_mutation_operation_unknown"
