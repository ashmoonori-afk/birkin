"""Extract readable HTML text and source-reported document dates."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import zlib

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


class ContentDecodingError(ValueError):
    """The response encoding is unsupported or expands beyond the safe cap."""


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    text: str
    published_at: str | None
    modified_at: str | None


class _DocumentParser(HTMLParser):
    _SKIP = {"script", "style", "noscript", "head"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.published_at: str | None = None
        self.modified_at: str | None = None
        self._skip_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
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
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self.parts.append(text)


def extract_document(body: str) -> ExtractedDocument:
    parser = _DocumentParser()
    parser.feed(body)
    return ExtractedDocument(
        text="\n".join(parser.parts),
        published_at=parser.published_at,
        modified_at=parser.modified_at,
    )


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
