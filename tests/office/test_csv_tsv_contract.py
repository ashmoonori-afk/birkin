from __future__ import annotations

import hashlib

import pytest

from birkin.office.csv_safety import (
    CsvDialect,
    CsvEncoding,
    CsvExportPlan,
    CsvImportPlan,
    CsvNewline,
    CsvSniffPolicy,
    export_delimited,
    import_delimited,
)
from birkin.office.errors import DocumentError, DocumentErrorCode


@pytest.mark.parametrize(
    ("encoding", "codec", "prefix"),
    [
        (CsvEncoding.UTF8, "utf-8", b""),
        (CsvEncoding.UTF8_BOM, "utf-8", b"\xef\xbb\xbf"),
        (CsvEncoding.CP949, "cp949", b""),
        (CsvEncoding.EUC_KR, "euc-kr", b""),
        (CsvEncoding.UTF16_LE, "utf-16-le", b""),
        (CsvEncoding.UTF16_BE, "utf-16-be", b""),
    ],
)
def test_real_encoded_bytes_round_trip_exactly(
    encoding: CsvEncoding, codec: str, prefix: bytes
) -> None:
    rows = (("이름", "메모"), ("가", "쉼표, 탭\t 따옴표 \""))
    plan = CsvExportPlan(
        encoding=encoding,
        dialect=CsvDialect(delimiter=";"),
        newline=CsvNewline.LF,
        spreadsheet_target=False,
    )
    exported = export_delimited(rows, plan)
    assert exported.data.startswith(prefix)
    assert exported.data.removeprefix(prefix).decode(codec)
    assert exported.output_sha256 == hashlib.sha256(exported.data).hexdigest()

    imported = import_delimited(
        exported.data,
        CsvImportPlan(encoding=encoding, dialect=plan.dialect, newline=CsvNewline.LF),
    )
    assert imported.rows == rows
    assert imported.source_sha256 == exported.output_sha256


@pytest.mark.parametrize("newline", list(CsvNewline))
def test_explicit_physical_newline_contract(newline: CsvNewline) -> None:
    if newline is CsvNewline.MIXED:
        payload = b'a,b\r\n1,"two\nlines"\r3,4\n'
        expected = (("a", "b"), ("1", "two\nlines"), ("3", "4"))
    else:
        token = {CsvNewline.LF: b"\n", CsvNewline.CRLF: b"\r\n", CsvNewline.CR: b"\r"}[newline]
        payload = token.join((b"a,b", b'1,"two"', b"3,4")) + token
        expected = (("a", "b"), ("1", "two"), ("3", "4"))
    assert import_delimited(payload, CsvImportPlan(newline=newline)).rows == expected


def test_quotes_escaped_quotes_multiline_and_all_delimiters_preserve_cells() -> None:
    rows = (("a", 'said "yes"', "line 1\nline 2"), ("", "x", "y"))
    for delimiter in (",", "\t", ";", "|"):
        dialect = CsvDialect(delimiter=delimiter)
        result = export_delimited(
            rows,
            CsvExportPlan(dialect=dialect, newline=CsvNewline.CR, spreadsheet_target=False),
        )
        assert import_delimited(
            result.data,
            CsvImportPlan(dialect=dialect, newline=CsvNewline.MIXED),
        ).rows == rows


def test_malformed_encoding_control_bytes_and_wrong_newline_are_refused() -> None:
    cases = [
        (b"a,\xff\n", CsvImportPlan()),
        (b"a,\x00b\n", CsvImportPlan()),
        (b"a,b\r\n", CsvImportPlan(newline=CsvNewline.LF)),
    ]
    for payload, plan in cases:
        with pytest.raises(DocumentError) as caught:
            _ = import_delimited(payload, plan)
        assert caught.value.code is DocumentErrorCode.INVALID_INPUT
        assert caught.value.artifact_sha256 == hashlib.sha256(payload).hexdigest()


def test_sniff_is_opt_in_bounded_and_refuses_ambiguous_delimiters() -> None:
    pipe = b"a|b\n1|2\n"
    assert import_delimited(pipe, CsvImportPlan()).rows == (("a|b",), ("1|2",))
    sniffed = import_delimited(
        pipe,
        CsvImportPlan(sniff=CsvSniffPolicy(candidates=(",", "\t", ";", "|"), max_bytes=64)),
    )
    assert sniffed.rows == (("a", "b"), ("1", "2"))
    assert sniffed.plan.dialect.delimiter == "|"

    with pytest.raises(DocumentError) as caught:
        _ = import_delimited(
            b"a,b;c\n1,2;3\n",
            CsvImportPlan(sniff=CsvSniffPolicy(candidates=(",", ";"), max_bytes=64)),
        )
    assert caught.value.code is DocumentErrorCode.INVALID_INPUT
    assert caught.value.details["candidates"] == [",", ";"]


def test_injection_is_checked_only_after_decode_and_logical_parse() -> None:
    payload = 'name;payload\r\n홍길동;" =1+1"\r\n'.encode("cp949")
    result = import_delimited(
        payload,
        CsvImportPlan(
            encoding=CsvEncoding.CP949,
            dialect=CsvDialect(delimiter=";"),
            newline=CsvNewline.CRLF,
        ),
    )
    assert result.rows[1][1] == " =1+1"
    assert [(item.row, item.column, item.trigger) for item in result.risks] == [(2, 2, "=")]

    with pytest.raises(DocumentError) as caught:
        _ = export_delimited(result.rows, CsvExportPlan(dialect=CsvDialect(delimiter=";")))
    assert caught.value.code is DocumentErrorCode.POLICY_DENIED


def test_neutralization_reports_every_changed_cell_and_receipts_are_deterministic() -> None:
    rows = (("=1", "safe"), ("@cmd", "+2"))
    plan = CsvExportPlan(encoding=CsvEncoding.UTF8_BOM, newline=CsvNewline.LF, neutralize=True)
    first = export_delimited(rows, plan)
    second = export_delimited(rows, plan)
    assert first == second
    assert [(c.row, c.column) for c in first.changed_cells] == [(1, 1), (2, 1), (2, 2)]
    assert first.data.startswith(b"\xef\xbb\xbf")
    assert first.receipt_sha256 == second.receipt_sha256
