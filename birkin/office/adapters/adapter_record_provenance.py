"""The sole assembled adapter-row registry consumed by catalog projections."""

from .approved_package_provenance import (
    DEFUSEDXML,
    LXML,
    OPENPYXL,
    PILLOW,
    PYPDF,
    PYPDFIUM2,
    PYTHON_DOCX,
    PYTHON_PPTX,
    RFC8785,
    XLSXWRITER,
)
from .candidate_package_provenance import (
    HANDOC_PARSER,
    HANDOC_WRITER,
    REPORTLAB,
)
from .operation_provenance import (
    PDF_OPERATIONS,
    SECURITY_LIMIT,
    hwpx_operations,
    opc_operations,
)
from .provenance_models import AdapterRecord

_ECMA_376 = (
    "https://ecma-international.org/publications-and-standards/standards/ecma-376/"
)

ADAPTER_RECORDS = (
    AdapterRecord(
        "docx",
        _ECMA_376,
        (PYTHON_DOCX, DEFUSEDXML, LXML, RFC8785),
        opc_operations(PYTHON_DOCX.install_probe),
        (SECURITY_LIMIT,),
        ("Tracked changes and arbitrary layout rewrites are not synthesized.",),
    ),
    AdapterRecord(
        "xlsx",
        _ECMA_376,
        (OPENPYXL, DEFUSEDXML, LXML, RFC8785),
        opc_operations(OPENPYXL.install_probe),
        (SECURITY_LIMIT,),
        ("Stored formulas are preserved but never claimed recalculated.",),
    ),
    AdapterRecord(
        "pptx",
        _ECMA_376,
        (PYTHON_PPTX, DEFUSEDXML, LXML, PILLOW, XLSXWRITER, RFC8785),
        opc_operations(PYTHON_PPTX.install_probe),
        (SECURITY_LIMIT,),
        ("Animations and arbitrary master rewrites are not synthesized.",),
    ),
    AdapterRecord(
        "pdf",
        "https://www.iso.org/standard/75839.html",
        (PYPDF, PYPDFIUM2, PILLOW, REPORTLAB, RFC8785),
        PDF_OPERATIONS,
        (
            "Optional PDF parsing and native-code PDFium require hostile-input review.",
        ),
        ("General PDF content rewriting remains unsupported.",),
    ),
    AdapterRecord(
        "hwpx",
        "https://tech.hancom.com/hwpxformat/",
        (HANDOC_PARSER, HANDOC_WRITER, RFC8785),
        hwpx_operations(),
        (SECURITY_LIMIT,),
        (
            "HanDoc-based parsing and blank authoring remain refused pending provenance.",
        ),
    ),
)
