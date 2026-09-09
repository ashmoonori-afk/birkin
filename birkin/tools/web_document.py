"""Extract readable HTML text and source-reported document dates."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
import json
import re
import zlib

from ..office.safe_xml import DefusedXmlException, ElementTree as ET

_PUBLISHED_KEYS = {
    "article:published_time",
    "datepublished",
    "publication_date",
    "publishdate",
    "pubdate",
}
_MODIFIED_KEYS = {
    "article:modified_time",
    "datemodified",
    "lastmod",
    "og:updated_time",
}
_MAX_DECOMPRESSED_BYTES = 2_000_000
_MAX_EXTRACTED_CHARS = 2_000_000
_MAX_LINK_TEXT = 256


class ContentDecodingError(ValueError):
    """The response encoding is unsupported or expands beyond the safe cap."""


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    text: str
    published_at: str | None
    modified_at: str | None
    alternate_urls: tuple[str, ...] = ()
    links: tuple[tuple[str, str], ...] = ()


class _DocumentParser(HTMLParser):
    _SKIP = {"script", "style", "noscript", "head", "nav"}
    _BLOCK = {
        "address", "article", "aside", "blockquote", "br", "dd", "div", "dl",
        "dt", "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5",
        "h6", "header", "hr", "li", "main", "ol", "p", "pre", "section",
        "table", "tbody", "tfoot", "thead", "tr", "ul", "nav",
    }

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._inline: list[str] = []
        self.published_at: str | None = None
        self.modified_at: str | None = None
        self.alternate_urls: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._anchor: tuple[str, list[str]] | None = None
        self._skip_depth = 0
        self._pre_depth = 0
        self._table_cell_depth = 0
        self._table_row_cells = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if self._skip_depth == 0 and tag in {"tr", "table"}:
            self._table_cell_depth = 0
            self._flush()
            self._table_row_cells = 0
        elif self._skip_depth == 0 and tag in {"td", "th"}:
            if self._table_row_cells:
                self._inline.append(" | ")
            self._table_row_cells += 1
            self._table_cell_depth = 1
        elif self._skip_depth == 0 and tag in self._BLOCK and self._table_cell_depth > 0:
            self._inline.append(" ")
        elif self._skip_depth == 0 and tag in self._BLOCK and self._table_cell_depth == 0:
            self._flush()
        if self._skip_depth == 0 and tag == "pre":
            self._pre_depth += 1
        if tag == "meta":
            values = {key.lower(): value for key, value in attrs if value}
            key = (
                values.get("property")
                or values.get("name")
                or values.get("itemprop")
                or ""
            ).lower()
            content = values.get("content")
            if content and key in _PUBLISHED_KEYS and self.published_at is None:
                self.published_at = content.strip()
            if content and key in _MODIFIED_KEYS and self.modified_at is None:
                self.modified_at = content.strip()
        if tag == "link":
            values = {key.lower(): value for key, value in attrs if value}
            rel = values.get("rel", "").casefold().split()
            media_type = values.get("type", "").casefold()
            href = values.get("href")
            if "alternate" in rel and href and any(kind in media_type for kind in ("rss", "atom")):
                self.alternate_urls.append(href)
        if tag == "a" and self._skip_depth == 0:
            self._finish_anchor()
            values = {key.lower(): value for key, value in attrs if value}
            href = values.get("href")
            if href:
                self._anchor = (href, [])
        if tag in self._SKIP and self._skip_depth == 0:
            self._finish_anchor()
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._skip_depth == 0:
            self._finish_anchor()
        if self._skip_depth == 0 and tag == "pre":
            if self._table_cell_depth == 0:
                self._flush()
            else:
                self._inline.append(" ")
            self._pre_depth = max(0, self._pre_depth - 1)
            return
        if self._skip_depth == 0 and tag in {"tr", "table"}:
            self._table_cell_depth = 0
            self._flush()
            self._table_row_cells = 0
            return
        if self._skip_depth == 0 and tag in {"td", "th"}:
            self._table_cell_depth = max(0, self._table_cell_depth - 1)
            return
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1
        elif self._skip_depth == 0 and tag in self._BLOCK and self._table_cell_depth == 0:
            self._flush()
        elif self._skip_depth == 0 and tag in self._BLOCK:
            self._inline.append(" ")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._inline.append(data)
            if self._anchor is not None:
                self._anchor[1].append(data)

    def _finish_anchor(self) -> None:
        if self._anchor is None:
            return
        href, parts = self._anchor
        text = " ".join("".join(parts).split())[:_MAX_LINK_TEXT]
        self.links.append((href, text))
        self._anchor = None

    def _flush(self) -> None:
        joined = "".join(self._inline)
        text = joined.strip("\r\n") if self._pre_depth else " ".join(joined.split())
        self._inline.clear()
        if text:
            self.parts.append(text)


def extract_document(body: str) -> ExtractedDocument:
    parser = _DocumentParser()
    parser.feed(body)
    parser._finish_anchor()
    parser._flush()
    return ExtractedDocument(
        text="\n".join(parser.parts),
        published_at=parser.published_at,
        modified_at=parser.modified_at,
        alternate_urls=tuple(parser.alternate_urls[:1]),
        links=tuple(parser.links),
    )


def extract_response(raw: bytes, content_type: str) -> ExtractedDocument:
    """Extract supported public document formats without adding a dependency."""
    lowered = content_type.lower()
    if "pdf" in lowered or raw.startswith(b"%PDF-"):
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ContentDecodingError("PDF text extraction is unavailable") from exc
        try:
            parts: list[str] = []
            length = 0
            for page in PdfReader(BytesIO(raw)).pages:
                part = page.extract_text() or ""
                length += len(part)
                if length > _MAX_EXTRACTED_CHARS:
                    raise ContentDecodingError("PDF extracted text exceeds 2000000 characters")
                parts.append(part)
            text = "\n".join(parts)
        except ContentDecodingError:
            raise
        except Exception as exc:
            raise ContentDecodingError("invalid PDF response") from exc
        return ExtractedDocument(text.strip(), None, None)
    body = raw.decode("utf-8", "replace")
    if "json" in lowered or body.lstrip().startswith(("{", "[")):
        try:
            value = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ContentDecodingError("invalid JSON response") from exc
        text = json.dumps(value, ensure_ascii=False, indent=2)
        if len(text) > _MAX_EXTRACTED_CHARS:
            raise ContentDecodingError("JSON extracted text exceeds 2000000 characters")
        return ExtractedDocument(text, None, None)
    if any(kind in lowered for kind in ("rss", "atom", "xml")):
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise ContentDecodingError("XML DTD and entity declarations are unsupported")
        try:
            root = ET.fromstring(body)
        except (ET.ParseError, DefusedXmlException) as exc:
            raise ContentDecodingError("invalid XML feed response") from exc
        parts = [text.strip() for text in root.itertext() if text.strip()]
        published = next((node.text.strip() for node in root.iter() if node.text and node.tag.rsplit("}", 1)[-1].lower() in {"published", "pubdate"}), None)
        modified = next((node.text.strip() for node in root.iter() if node.text and node.tag.rsplit("}", 1)[-1].lower() in {"updated", "lastbuilddate"}), None)
        text = "\n".join(parts)
        if len(text) > _MAX_EXTRACTED_CHARS:
            raise ContentDecodingError("XML extracted text exceeds 2000000 characters")
        return ExtractedDocument(text, published, modified)
    if "html" in lowered or body.lstrip().startswith("<"):
        return extract_document(body)
    return ExtractedDocument(re.sub(r"\x00", "", body).strip(), None, None)


def decode_http_body(raw: bytes, content_encoding: str) -> bytes:
    encoding = content_encoding.strip().lower()
    if not encoding or encoding == "identity":
        return raw
    if encoding == "gzip":
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    elif encoding == "deflate":
        decompressor = zlib.decompressobj()
    else:
        raise ContentDecodingError(
            f"unsupported Content-Encoding: {content_encoding}"
        )

    try:
        body = decompressor.decompress(raw, _MAX_DECOMPRESSED_BYTES + 1)
    except zlib.error as exc:
        raise ContentDecodingError(
            f"invalid compressed response: {exc}"
        ) from exc
    if decompressor.unconsumed_tail or len(body) > _MAX_DECOMPRESSED_BYTES:
        raise ContentDecodingError(
            "decompressed response exceeds 2000000 bytes"
        )
    body += decompressor.flush(_MAX_DECOMPRESSED_BYTES + 1 - len(body))
    if len(body) > _MAX_DECOMPRESSED_BYTES:
        raise ContentDecodingError(
            "decompressed response exceeds 2000000 bytes"
        )
    return body
