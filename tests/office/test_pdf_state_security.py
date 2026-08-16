from __future__ import annotations

import socket
from importlib.util import find_spec
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from birkin.office.adapters.pdf import PdfAdapter
from birkin.office.adapters.pdf_types import PdfMapping, array_items, mapping
from birkin.office.errors import DocumentError, DocumentErrorCode

if find_spec("pypdf") is None:
    pytest.skip("pypdf is not installed", allow_module_level=True)

if TYPE_CHECKING:
    from pypdf.constants import UserAccessPermissions


def _mapping(value: object) -> PdfMapping:
    result = mapping(value)
    assert result is not None
    return result


def _mapping_items(value: object) -> list[PdfMapping]:
    result = [_mapping(item) for item in array_items(value)]
    assert result
    return result


def _pdf(objects: list[bytes], *, root: int = 1) -> bytes:
    data = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode())
        data.extend(body)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root {root} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(data)


def _base(
    *,
    catalog: bytes = b"<< /Type /Catalog /Pages 2 0 R >>",
    page: bytes | None = None,
    extra: list[bytes] | None = None,
) -> bytes:
    content = b"BT /F1 12 Tf 72 720 Td (Hello PDF) Tj ET"
    default_page = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
    return _pdf(
        [
            catalog,
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            page or default_page,
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length "
            + str(len(content)).encode()
            + b" >>\nstream\n"
            + content
            + b"\nendstream",
            *(extra or []),
        ]
    )


def _write(path: Path, data: bytes) -> Path:
    _ = path.write_bytes(data)
    return path


def _image_pdf() -> bytes:
    image = b"\x00\x00\x00"
    drawing = b"q 100 0 0 100 0 0 cm /Im0 Do Q"
    return _pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Length 3 >>\nstream\n"
            + image
            + b"\nendstream",
            b"<< /Length "
            + str(len(drawing)).encode()
            + b" >>\nstream\n"
            + drawing
            + b"\nendstream",
        ]
    )


def _form_pdf(*, xfa: bool = False) -> bytes:
    acroform = b"<< /Fields [7 0 R]" + (b" /XFA 8 0 R" if xfa else b"") + b" >>"
    extras = [
        acroform,
        b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (name) /Rect [0 0 50 20] /P 3 0 R >>",
    ]
    if xfa:
        packet = b"<xdp:xdp xmlns:xdp='http://ns.adobe.com/xdp/'/>"
        extras.append(
            b"<< /Length "
            + str(len(packet)).encode()
            + b" >>\nstream\n"
            + packet
            + b"\nendstream"
        )
    return _base(
        catalog=b"<< /Type /Catalog /Pages 2 0 R /AcroForm 6 0 R >>",
        page=b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R /Annots [7 0 R] >>",
        extra=extras,
    )


def _signed_pdf() -> bytes:
    signature = (
        b"<< /Type /Sig /Filter /Adobe.PPKLite /SubFilter /adbe.pkcs7.detached "
        b"/ByteRange [0000000000 0000000000 0000000000 0000000000] "
        b"/Contents <01020304> /Reference [<< /TransformMethod /DocMDP /TransformParams << /Type /TransformParams /P 1 /V /1.2 >> >>] >>"
    )
    raw = _base(
        catalog=b"<< /Type /Catalog /Pages 2 0 R /AcroForm 6 0 R /Perms << /DocMDP 7 0 R >> >>",
        extra=[
            b"<< /Fields [8 0 R] /SigFlags 3 >>",
            signature,
            b"<< /FT /Sig /T (Approval) /V 7 0 R >>",
        ],
    )
    marker = b"/Contents <01020304>"
    start = raw.index(marker) + len(b"/Contents ")
    end = start + len(b"<01020304>")
    values = (0, start, end, len(raw) - end)
    encoded = b" ".join(f"{value:010d}".encode() for value in values)
    placeholder = b"0000000000 0000000000 0000000000 0000000000"
    assert len(encoded) == len(placeholder)
    return raw.replace(placeholder, encoded, 1)


def _active_pdf() -> bytes:
    return _base(
        catalog=b"<< /Type /Catalog /Pages 2 0 R /OpenAction 6 0 R /Names << /JavaScript << /Names [(startup) 7 0 R] >> /EmbeddedFiles << /Names [(payload.txt) 9 0 R] >> >> >>",
        extra=[
            b"<< /Type /Action /S /Launch /F (never-opened.bin) >>",
            b"<< /Type /Action /S /JavaScript /JS (app.alert('never')) >>",
            b"<< /Type /EmbeddedFile /Length 4 >>\nstream\ndata\nendstream",
            b"<< /Type /Filespec /F (payload.txt) /EF << /F 8 0 R >> >>",
        ],
    )


def _encrypted(
    data: bytes, *, permissions: UserAccessPermissions | None = None
) -> bytes:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(BytesIO(data), strict=True))
    if permissions is None:
        writer.encrypt("correct horse", algorithm="RC4-128")
    else:
        writer.encrypt(
            "correct horse", algorithm="RC4-128", permissions_flag=permissions
        )
    output = BytesIO()
    _ = writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize(
    "trailer",
    [b"%%EOF\n", b"startxref\n0\n%%EOF\n"],
    ids=["xref-less", "malformed-xref"],
)
def test_structurally_invalid_pdf_never_bypasses_strict_security_inspection(
    tmp_path: Path, trailer: bytes
) -> None:
    raw = b"".join(
        (
            b"%PDF-1.7\n1 0 obj << /Encrypt 2 0 R /OpenAction 3 0 R >> endobj\n",
            b"BT 72 720 Td (BYPASS) Tj ET\n/JavaScript /JS (never)\n",
            trailer,
        )
    )
    source = _write(tmp_path / "malformed.pdf", raw)
    before = source.read_bytes()

    with pytest.raises(DocumentError) as inspected:
        _ = PdfAdapter().inspect(source)
    with pytest.raises(DocumentError) as extracted:
        _ = PdfAdapter().extract(source)

    assert inspected.value.code is DocumentErrorCode.PACKAGE_INVALID
    assert extracted.value.code is DocumentErrorCode.PACKAGE_INVALID
    assert inspected.value.details["reason"] == "pdf_structure_invalid"
    assert extracted.value.details["reason"] == "pdf_structure_invalid"
    assert source.read_bytes() == before


def test_content_and_form_states_are_orthogonal_and_truthful(tmp_path: Path) -> None:
    native = PdfAdapter().inspect(_write(tmp_path / "native.pdf", _base()))
    scanned_path = _write(tmp_path / "scan.pdf", _image_pdf())
    scanned = PdfAdapter().inspect(scanned_path)
    acro = PdfAdapter().inspect(_write(tmp_path / "acro.pdf", _form_pdf()))
    xfa_path = _write(tmp_path / "xfa.pdf", _form_pdf(xfa=True))
    xfa = PdfAdapter().inspect(xfa_path)

    acro_forms = _mapping(acro["forms"])
    xfa_forms = _mapping(xfa["forms"])
    scanned_caps = _mapping(scanned["capabilities"])
    xfa_caps = _mapping(xfa["capabilities"])
    scanned_extract = _mapping(scanned_caps.get("extract"))
    xfa_fill = _mapping(xfa_caps.get("fill"))
    assert (native["content_type"], native["form_type"]) == (
        "native_text",
        "flat_or_no_form",
    )
    assert (scanned["content_type"], scanned["form_type"]) == (
        "image_only",
        "flat_or_no_form",
    )
    assert acro["form_type"] == "acroform" and acro_forms.get("field_count") == 1
    assert xfa["form_type"] == "xfa" and xfa_forms.get("has_acroform") is True
    assert scanned_extract.get("reason") == "pdf_image_only_requires_ocr"
    assert xfa_fill.get("reason") == "pdf_xfa_unsupported"
    with pytest.raises(DocumentError, match="OCR") as scanned_error:
        _ = PdfAdapter().extract(scanned_path)
    with pytest.raises(DocumentError) as xfa_error:
        _ = PdfAdapter().extract(xfa_path)
    assert scanned_error.value.details["reason"] == "pdf_image_only_requires_ocr"
    assert xfa_error.value.details["reason"] == "pdf_xfa_content_unsupported"


def test_encrypted_pdf_requires_exact_user_credential_for_content(
    tmp_path: Path,
) -> None:
    source = _write(tmp_path / "protected.pdf", _encrypted(_base()))
    locked = PdfAdapter().inspect(source)
    assert locked["encrypted"] is True and locked["credential_required"] is True
    assert locked["content_type"] == "unknown_encrypted"
    locked_caps = _mapping(locked["capabilities"])
    locked_extract = _mapping(locked_caps.get("extract"))
    locked_fill = _mapping(locked_caps.get("fill"))
    assert locked_extract.get("reason") == "pdf_password_required"
    assert locked_fill.get("reason") == "pdf_password_required"
    with pytest.raises(DocumentError) as missing:
        _ = PdfAdapter().extract(source)
    assert missing.value.code is DocumentErrorCode.PERMISSION_DENIED
    assert missing.value.details["reason"] == "pdf_password_required"
    with pytest.raises(DocumentError) as invalid:
        _ = PdfAdapter(password="wrong").inspect(source)
    assert invalid.value.details["reason"] == "pdf_invalid_password"
    unlocked = PdfAdapter(password="correct horse")
    assert unlocked.inspect(source)["content_type"] == "native_text"
    assert unlocked.extract(source)[0]["text"] == "Hello PDF"

    from pypdf.constants import UserAccessPermissions

    restricted = _write(
        tmp_path / "restricted.pdf",
        _encrypted(_base(), permissions=UserAccessPermissions.PRINT),
    )
    restricted_adapter = PdfAdapter(password="correct horse")
    security = _mapping(restricted_adapter.inspect(restricted)["security"])
    assert security.get("text_extraction_allowed") is False
    with pytest.raises(DocumentError) as denied:
        _ = restricted_adapter.extract(restricted)
    assert denied.value.details["reason"] == "pdf_extraction_permission_denied"


def test_signature_inventory_does_not_claim_verification_or_trust(
    tmp_path: Path,
) -> None:
    result = PdfAdapter().inspect(_write(tmp_path / "signed-like.pdf", _signed_pdf()))
    signatures = _mapping(result["signatures"])
    signature = _mapping_items(signatures.get("items"))[0]
    assert result["signed"] is True
    assert signature.get("signature_bytes_present") is True
    assert signature.get("byte_range_coverage") == "file_boundaries_with_exclusions"
    assert signature.get("byte_range_valid") is True
    assert signature.get("byte_range_starts_at_zero") is True
    assert signature.get("byte_range_ends_at_eof") is True
    assert signature.get("doc_mdp") is True
    assert signature.get("doc_mdp_permission") == 1
    assert signature.get("cryptographic_verification") == "unsupported"
    assert signature.get("trust_evaluation") == "unsupported"


def test_active_content_is_only_inventoried_offline_and_source_is_immutable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _write(tmp_path / "active.pdf", _active_pdf())
    before = source.read_bytes()

    def no_network(*args: object, **kwargs: object) -> None:
        _ = args, kwargs
        raise AssertionError("PDF inspection attempted network access")

    monkeypatch.setattr(socket, "socket", no_network)
    result = PdfAdapter().inspect(source)
    active = _mapping_items(result["active_content"])
    kinds = {item.get("kind") for item in active}
    assert {
        "open_action",
        "Launch",
        "JavaScript",
        "javascript_name_tree",
        "embedded_files",
        "embedded_file",
    } <= kinds
    assert all(item.get("executed") is False for item in active)
    assert source.read_bytes() == before
    assert list(tmp_path.iterdir()) == [source]
    with pytest.raises(DocumentError) as refused:
        PdfAdapter().patch(source, {})
    assert refused.value.code is DocumentErrorCode.UNSUPPORTED_EDIT
    assert refused.value.details["reason"] == "pdf_general_mutation_unsupported"
