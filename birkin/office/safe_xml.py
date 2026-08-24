"""Small stdlib XML boundary for baseline Office package parsing."""

from __future__ import annotations

import re
from os import PathLike
from typing import Any, Protocol, TypeAlias, TypeVar
from xml.etree import ElementTree as _ET

_DefusedXmlExceptionType: type[Exception]
try:
    from defusedxml.common import (
        DefusedXmlException as _ImportedDefusedXmlException,
    )
    from defusedxml.ElementTree import DefusedXMLParser as _DefusedXMLParser
    _DefusedXmlExceptionType = _ImportedDefusedXmlException
except ModuleNotFoundError:
    _DefusedXmlExceptionType = Exception
    _DefusedXMLParser = None


class DefusedXmlException(ValueError):
    """Compatibility error raised for prohibited XML declarations."""


_DTD_DECLARATION = re.compile(r"<!\s*DOCTYPE\b", re.IGNORECASE)
_ENTITY_DECLARATION = re.compile(r"<!\s*ENTITY\b", re.IGNORECASE)
_EXTERNAL_DECLARATION = re.compile(
    r"<!\s*(?:DOCTYPE|ENTITY)\b[^>]*\b(?:SYSTEM|PUBLIC)\b",
    re.IGNORECASE | re.DOTALL,
)
_XML_COMMENT_OR_CDATA = re.compile(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>", re.DOTALL)
_XmlData = TypeVar("_XmlData", bytes, str, covariant=True)


class _XmlReader(Protocol[_XmlData]):
    def read(self, size: int = -1, /) -> _XmlData: ...


XmlSource: TypeAlias = (
    str
    | bytes
    | int
    | PathLike[str]
    | PathLike[bytes]
    | _XmlReader[str]
    | _XmlReader[bytes]
)


def _guard_text(
    data: bytes | str,
    *,
    forbid_dtd: bool,
    forbid_entities: bool,
    forbid_external: bool,
) -> None:
    if isinstance(data, str):
        text = data
    elif data.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        text = data.decode("utf-32")
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    elif data.startswith(b"\x00\x00\x00<"):
        text = data.decode("utf-32-be")
    elif data.startswith(b"<\x00\x00\x00"):
        text = data.decode("utf-32-le")
    elif data.startswith(b"\x00<"):
        text = data.decode("utf-16-be")
    elif data.startswith(b"<\x00"):
        text = data.decode("utf-16-le")
    else:
        text = data.decode("latin-1")

    guarded = _XML_COMMENT_OR_CDATA.sub("", text)
    if (
        forbid_dtd
        and _DTD_DECLARATION.search(guarded)
        or forbid_entities
        and _ENTITY_DECLARATION.search(guarded)
        or forbid_external
        and _EXTERNAL_DECLARATION.search(guarded)
    ):
        raise DefusedXmlException("DTD and entity declarations are forbidden")


def fromstring(
    data: bytes | str,
    *,
    forbid_dtd: bool = True,
    forbid_entities: bool = True,
    forbid_external: bool = True,
) -> _ET.Element:
    parser = XMLParser(
        forbid_dtd=forbid_dtd,
        forbid_entities=forbid_entities,
        forbid_external=forbid_external,
    )
    parser.feed(data)
    return parser.close()


def parse(
    source: XmlSource,
    *,
    forbid_dtd: bool = True,
    forbid_entities: bool = True,
    forbid_external: bool = True,
) -> _ET.ElementTree[_ET.Element[str]]:
    parser = XMLParser(
        forbid_dtd=forbid_dtd,
        forbid_entities=forbid_entities,
        forbid_external=forbid_external,
    )
    if isinstance(source, (str, bytes, int, PathLike)):
        with open(source, "rb") as stream:
            payload = stream.read()
    else:
        payload = source.read()
    parser.feed(payload)
    return _ET.ElementTree(parser.close())


class _GuardedXMLParser:
    def __init__(
        self,
        *,
        target: Any = None,
        encoding: str | None = None,
        forbid_dtd: bool = True,
        forbid_entities: bool = True,
        forbid_external: bool = True,
    ) -> None:
        self._target = target
        self._encoding = encoding
        self._forbid_dtd = forbid_dtd
        self._forbid_entities = forbid_entities
        self._forbid_external = forbid_external
        self._forbid_declarations = (
            forbid_dtd
            or forbid_entities
            or forbid_external
        )
        self._chunks: list[bytes | str] = []

    def feed(self, data: bytes | str) -> None:
        self._chunks.append(data)

    def close(self) -> _ET.Element:
        text_chunks = [
            chunk for chunk in self._chunks if isinstance(chunk, str)
        ]
        if text_chunks:
            if len(text_chunks) != len(self._chunks):
                raise TypeError("cannot mix text and bytes XML chunks")
            payload: bytes | str = "".join(text_chunks)
        else:
            payload = b"".join(
                chunk for chunk in self._chunks if isinstance(chunk, bytes)
            )
        if _DefusedXMLParser is not None:
            parser = _DefusedXMLParser(
                target=self._target,
                encoding=self._encoding,
                forbid_dtd=self._forbid_dtd,
                forbid_entities=self._forbid_entities,
                forbid_external=self._forbid_external,
            )
            try:
                parser.feed(payload)
                return parser.close()
            except _DefusedXmlExceptionType as exc:
                raise DefusedXmlException(
                    "DTD and entity declarations are forbidden"
                ) from exc
        if self._forbid_declarations:
            _guard_text(
                payload,
                forbid_dtd=self._forbid_dtd,
                forbid_entities=self._forbid_entities,
                forbid_external=self._forbid_external,
            )
        parser = _ET.XMLParser(target=self._target, encoding=self._encoding)
        parser.feed(payload)
        return parser.close()


def XMLParser(
    *,
    target: Any = None,
    encoding: str | None = None,
    forbid_dtd: bool = True,
    forbid_entities: bool = True,
    forbid_external: bool = True,
) -> _GuardedXMLParser:
    """Build a streaming parser that validates declarations before parsing."""

    return _GuardedXMLParser(
        target=target,
        encoding=encoding,
        forbid_dtd=forbid_dtd,
        forbid_entities=forbid_entities,
        forbid_external=forbid_external,
    )


class _GuardedElementTree(_ET.ElementTree):
    def parse(
        self,
        source: XmlSource,
        parser: _ET.XMLParser | None = None,
    ) -> _ET.Element:
        if parser is not None:
            raise TypeError("custom XML parsers are not supported")
        root = parse(source).getroot()
        self._setroot(root)
        return root


class _ElementTreeFacade:
    ParseError = _ET.ParseError
    Element = _ET.Element
    ElementTree = _GuardedElementTree
    XMLParser = staticmethod(XMLParser)
    fromstring = staticmethod(fromstring)
    parse = staticmethod(parse)
    register_namespace = staticmethod(_ET.register_namespace)
    tostring = staticmethod(_ET.tostring)


ElementTree = _ElementTreeFacade()
ParseError = _ET.ParseError

__all__ = [
    "DefusedXmlException",
    "ElementTree",
    "ParseError",
    "XMLParser",
    "fromstring",
    "parse",
]
