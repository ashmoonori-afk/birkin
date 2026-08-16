"""Cross-version normalization around Python's CSV reader and writer."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from typing import Literal

CsvQuoting = Literal[0, 1, 2, 3]


def parse_csv_rows(
    text: str,
    *,
    delimiter: str,
    quotechar: str | None,
    escapechar: str | None,
    doublequote: bool,
    quoting: CsvQuoting,
) -> tuple[tuple[str, ...], ...]:
    sentinel: str | None = None
    source = text
    if "\x00" in text:
        sentinel = next(
            (chr(code) for code in range(0xE000, 0xF900) if chr(code) not in text),
            None,
        )
        if sentinel is None:
            raise csv.Error("no collision-free NUL sentinel is available")
        source = text.replace("\x00", sentinel)
    rows = csv.reader(
        io.StringIO(source, newline=""),
        delimiter=delimiter,
        quotechar=quotechar,
        escapechar=escapechar,
        doublequote=doublequote,
        quoting=quoting,
        strict=True,
    )
    if sentinel is None:
        return tuple(tuple(row) for row in rows)
    return tuple(tuple(cell.replace(sentinel, "\x00") for cell in row) for row in rows)


def parse_standard_rows(text: str, delimiter: str) -> tuple[tuple[str, ...], ...]:
    return parse_csv_rows(
        text, delimiter=delimiter, quotechar='"', escapechar=None,
        doublequote=True, quoting=csv.QUOTE_MINIMAL,
    )


def render_csv_rows(
    rows: Iterable[Sequence[str]],
    *,
    delimiter: str,
    quotechar: str | None,
    escapechar: str | None,
    doublequote: bool,
    quoting: CsvQuoting,
    lineterminator: str,
) -> str:
    chunks: list[str] = []
    for row in rows:
        stream = io.StringIO(newline="")
        writer = csv.writer(
            stream,
            delimiter=delimiter,
            quotechar=quotechar,
            escapechar=escapechar,
            doublequote=doublequote,
            quoting=quoting,
            lineterminator="\r\n",
        )
        writer.writerow(row)
        chunks.append(stream.getvalue().removesuffix("\r\n") + lineterminator)
    return "".join(chunks)
