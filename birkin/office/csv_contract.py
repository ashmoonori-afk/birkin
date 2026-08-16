"""Explicit byte, dialect, and newline contracts for delimited text."""

from __future__ import annotations

import codecs
import csv
import hashlib
import json
import unicodedata
from dataclasses import dataclass, replace
from enum import Enum
from typing import Literal

from .csv_runtime import parse_csv_rows
from .errors import DocumentError, DocumentErrorCode


class CsvEncoding(str, Enum):
    UTF8 = "utf-8"
    UTF8_BOM = "utf-8-bom"
    CP949 = "cp949"
    EUC_KR = "euc-kr"
    UTF16_LE = "utf-16-le"
    UTF16_BE = "utf-16-be"


class CsvNewline(str, Enum):
    LF = "LF"
    CRLF = "CRLF"
    CR = "CR"
    MIXED = "MIXED"


class CsvQuotePolicy(str, Enum):
    MINIMAL = "minimal"
    ALL = "all"
    NONE = "none"


_QUOTING: dict[CsvQuotePolicy, Literal[0, 1, 2, 3]] = {CsvQuotePolicy.MINIMAL: csv.QUOTE_MINIMAL, CsvQuotePolicy.ALL: csv.QUOTE_ALL, CsvQuotePolicy.NONE: csv.QUOTE_NONE}
_NEWLINES = {CsvNewline.LF: "\n", CsvNewline.CRLF: "\r\n", CsvNewline.CR: "\r"}
_CODECS = {CsvEncoding.UTF8: "utf-8", CsvEncoding.UTF8_BOM: "utf-8",
           CsvEncoding.CP949: "cp949", CsvEncoding.EUC_KR: "euc-kr",
           CsvEncoding.UTF16_LE: "utf-16-le", CsvEncoding.UTF16_BE: "utf-16-be"}
_BOMS = {CsvEncoding.UTF8_BOM: codecs.BOM_UTF8,
         CsvEncoding.UTF16_LE: codecs.BOM_UTF16_LE,
         CsvEncoding.UTF16_BE: codecs.BOM_UTF16_BE}


def _character(value: str | None, name: str, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if value is None or len(value) != 1 or value in "\x00\r\n":
        raise ValueError(f"{name} must be one non-NUL, non-line-break character")


@dataclass(frozen=True, slots=True)
class CsvDialect:
    delimiter: str = ","
    quotechar: str | None = '"'
    escapechar: str | None = None
    doublequote: bool = True
    quote_policy: CsvQuotePolicy = CsvQuotePolicy.MINIMAL

    def __post_init__(self) -> None:
        _character(self.delimiter, "delimiter")
        _character(self.quotechar, "quotechar", optional=self.quote_policy is CsvQuotePolicy.NONE)
        _character(self.escapechar, "escapechar", optional=True)
        if self.delimiter in {self.quotechar, self.escapechar}:
            raise ValueError("delimiter, quotechar, and escapechar must be distinct")
        if self.quote_policy is CsvQuotePolicy.NONE and self.escapechar is None:
            raise ValueError("quote_policy NONE requires an escapechar")


@dataclass(frozen=True, slots=True)
class CsvSniffPolicy:
    candidates: tuple[str, ...] = (",", "\t", ";", "|")
    max_bytes: int = 8192

    def __post_init__(self) -> None:
        if not self.candidates or len(set(self.candidates)) != len(self.candidates):
            raise ValueError("sniff candidates must be non-empty and unique")
        for candidate in self.candidates:
            _character(candidate, "sniff delimiter")
        if not 32 <= self.max_bytes <= 1_048_576:
            raise ValueError("sniff max_bytes must be between 32 and 1048576")


@dataclass(frozen=True, slots=True)
class CsvImportPlan:
    encoding: CsvEncoding = CsvEncoding.UTF8
    dialect: CsvDialect = CsvDialect()
    newline: CsvNewline = CsvNewline.MIXED
    strict_decode: bool = True
    sniff: CsvSniffPolicy | None = None

    def __post_init__(self) -> None:
        if not self.strict_decode:
            raise ValueError("only strict decoding is supported")


@dataclass(frozen=True, slots=True)
class CsvExportPlan:
    encoding: CsvEncoding = CsvEncoding.UTF8
    dialect: CsvDialect = CsvDialect()
    newline: CsvNewline = CsvNewline.CRLF
    spreadsheet_target: bool = True
    neutralize: bool = False

    def __post_init__(self) -> None:
        if self.newline is CsvNewline.MIXED:
            raise ValueError("export newline must be LF, CRLF, or CR")
        if self.neutralize and not self.spreadsheet_target:
            raise ValueError("neutralization is only defined for spreadsheet-target export")


@dataclass(frozen=True, slots=True)
class ParsedDelimited:
    rows: tuple[tuple[str, ...], ...]
    plan: CsvImportPlan
    source_sha256: str


def _error(message: str, digest: str, **details: object) -> DocumentError:
    return DocumentError(
        DocumentErrorCode.INVALID_INPUT,
        "import",
        message,
        artifact_sha256=digest,
        details=details,
    )


def _decode(data: bytes, encoding: CsvEncoding, digest: str) -> str:
    bom = _BOMS.get(encoding)
    payload = data
    if encoding is CsvEncoding.UTF8 and data.startswith(codecs.BOM_UTF8):
        raise _error("UTF-8 BOM requires the utf-8-bom encoding plan", digest)
    if encoding is CsvEncoding.UTF8_BOM:
        if bom is None or not data.startswith(bom):
            raise _error("utf-8-bom input is missing its BOM", digest)
        payload = data[len(bom) :]
    elif encoding in {CsvEncoding.UTF16_LE, CsvEncoding.UTF16_BE}:
        opposite = codecs.BOM_UTF16_BE if encoding is CsvEncoding.UTF16_LE else codecs.BOM_UTF16_LE
        if data.startswith(opposite):
            raise _error("UTF-16 BOM conflicts with the encoding plan", digest)
        if bom is not None and data.startswith(bom):
            payload = data[len(bom) :]
    try:
        return payload.decode(_CODECS[encoding], errors="strict")
    except UnicodeDecodeError as exc:
        raise _error("delimited input does not match the strict encoding plan", digest) from exc


def _validate_text(text: str, newline: CsvNewline, digest: str) -> None:
    for character in text:
        if character not in "\t\r\n" and unicodedata.category(character) == "Cc":
            raise _error("delimited input contains a forbidden control character", digest)
    kinds: set[CsvNewline] = set()
    index = 0
    while index < len(text):
        if text[index : index + 2] == "\r\n":
            kinds.add(CsvNewline.CRLF)
            index += 2
        elif text[index] == "\r":
            kinds.add(CsvNewline.CR)
            index += 1
        elif text[index] == "\n":
            kinds.add(CsvNewline.LF)
            index += 1
        else:
            index += 1
    if newline is not CsvNewline.MIXED and kinds - {newline}:
        raise _error(
            "physical newline does not match the import plan",
            digest,
            expected=newline.value,
            observed=sorted(item.value for item in kinds),
        )


def _reader(text: str, dialect: CsvDialect) -> tuple[tuple[str, ...], ...]:
    return parse_csv_rows(
        text,
        delimiter=dialect.delimiter,
        quotechar=dialect.quotechar,
        escapechar=dialect.escapechar,
        doublequote=dialect.doublequote,
        quoting=_QUOTING[dialect.quote_policy],
    )


def _sniff(
    text: str, plan: CsvImportPlan, policy: CsvSniffPolicy, digest: str
) -> CsvDialect:
    sample_bytes = text.encode(_CODECS[plan.encoding])[: policy.max_bytes]
    decoder = codecs.getincrementaldecoder(_CODECS[plan.encoding])(errors="strict")
    sample = decoder.decode(sample_bytes, final=False)
    viable: list[str] = []
    for candidate in policy.candidates:
        try:
            rows = _reader(sample, replace(plan.dialect, delimiter=candidate))
        except csv.Error:
            continue
        widths = {len(row) for row in rows if row}
        if widths and min(widths) > 1 and len(widths) == 1:
            viable.append(candidate)
    if len(viable) != 1:
        raise _error("delimiter sniff is ambiguous", digest, candidates=viable)
    return replace(plan.dialect, delimiter=viable[0])


def parse_delimited(data: bytes, plan: CsvImportPlan) -> ParsedDelimited:
    digest = hashlib.sha256(data).hexdigest()
    text = _decode(data, plan.encoding, digest)
    _validate_text(text, plan.newline, digest)
    dialect = _sniff(text, plan, plan.sniff, digest) if plan.sniff is not None else plan.dialect
    resolved = replace(plan, dialect=dialect)
    try:
        rows = _reader(text, dialect)
    except csv.Error as exc:
        raise _error("delimited input violates the strict dialect plan", digest) from exc
    return ParsedDelimited(rows, resolved, digest)


def encode_delimited(text: str, encoding: CsvEncoding) -> bytes:
    try:
        payload = text.encode(_CODECS[encoding], errors="strict")
    except UnicodeEncodeError as exc:
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT, "export", "cell text cannot be represented in the export encoding"
        ) from exc
    return (_BOMS[encoding] + payload) if encoding is CsvEncoding.UTF8_BOM else payload


def receipt_hash(receipt: dict[str, object]) -> str:
    canonical = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def newline_text(newline: CsvNewline) -> str:
    return _NEWLINES[newline]


def quoting_value(policy: CsvQuotePolicy) -> Literal[0, 1, 2, 3]:
    return _QUOTING[policy]
