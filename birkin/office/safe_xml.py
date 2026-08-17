"""Small stdlib XML boundary for baseline Office package parsing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import BinaryIO
from xml.etree import ElementTree as _ET

_FORBIDDEN_DECLARATION = re.compile(
    rb"<!\s*(?:DOCTYPE|ENTITY)\b",
    re.IGNORECASE,
)


class DefusedXmlException(ValueError):
    """Compatibility error raised for prohibited XML declarations."""


def _guard(data: bytes) -> None:
    if _FORBIDDEN_DECLARATION.search(data):
        raise DefusedXmlException("DTD and entity declarations are forbidden")


def fromstring(
    data: bytes | str,
    *,
    forbid_dtd: bool = True,
    forbid_entities: bool = True,
    forbid_external: bool = True,
) -> _ET.Element:
    _ = forbid_dtd, forbid_entities, forbid_external
    encoded = data.encode("utf-8") if isinstance(data, str) else data
    _guard(encoded)
    return _ET.fromstring(encoded)


def parse(
    source: str | Path | BinaryIO,
    *,
    forbid_dtd: bool = True,
    forbid_entities: bool = True,
    forbid_external: bool = True,
) -> _ET.ElementTree:
    _ = forbid_dtd, forbid_entities, forbid_external
    if hasattr(source, "read"):
        payload = source.read()
    else:
        payload = Path(source).read_bytes()
    encoded = payload.encode("utf-8") if isinstance(payload, str) else payload
    _guard(encoded)
    return _ET.ElementTree(_ET.fromstring(encoded))


class _GuardedXMLParser:
    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs.pop("forbid_dtd", None)
        kwargs.pop("forbid_entities", None)
        kwargs.pop("forbid_external", None)
        self._args = args
        self._kwargs = kwargs
        self._chunks: list[bytes | str] = []

    def feed(self, data: bytes | str) -> None:
        self._chunks.append(data)

    def close(self) -> _ET.Element:
        if any(isinstance(chunk, str) for chunk in self._chunks):
            if not all(isinstance(chunk, str) for chunk in self._chunks):
                raise TypeError("cannot mix text and bytes XML chunks")
            payload: bytes | str = "".join(
                str(chunk) for chunk in self._chunks
            )
        else:
            payload = b"".join(
                bytes(chunk) for chunk in self._chunks
            )
        encoded = payload.encode("utf-8") if isinstance(payload, str) else payload
        _guard(encoded)
        parser = _ET.XMLParser(*self._args, **self._kwargs)
        parser.feed(payload)
        return parser.close()


def XMLParser(*args: object, **kwargs: object) -> _GuardedXMLParser:
    """Build a streaming parser that validates declarations before parsing."""

    return _GuardedXMLParser(*args, **kwargs)


class _ElementTreeFacade:
    ParseError = _ET.ParseError
    Element = _ET.Element
    ElementTree = _ET.ElementTree
    XMLParser = staticmethod(XMLParser)
    fromstring = staticmethod(fromstring)
    parse = staticmethod(parse)
    register_namespace = staticmethod(_ET.register_namespace)
    tostring = staticmethod(_ET.tostring)

    def __getattr__(self, name: str) -> object:
        return getattr(_ET, name)


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
