"""Runtime-validated structural types for pypdf's dynamic object model."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class PdfResolvable(Protocol):
    def get_object(self) -> object | None: ...


@runtime_checkable
class PdfIndirect(PdfResolvable, Protocol):
    idnum: int
    generation: int


@runtime_checkable
class PdfMapping(Protocol):
    def __contains__(self, key: object, /) -> bool: ...

    def get(self, key: object, default: object = None, /) -> object: ...

    def items(self) -> Iterable[tuple[object, object]]: ...

    def values(self) -> Iterable[object]: ...


@runtime_checkable
class PdfArray(Protocol):
    def __len__(self) -> int: ...

    def __getitem__(self, index: int, /) -> object: ...


@runtime_checkable
class PdfTextExtractor(Protocol):
    def extract_text(self) -> str: ...


@runtime_checkable
class PdfPermissionValidity(Protocol):
    @property
    def are_permissions_valid(self) -> object: ...


@dataclass(frozen=True, slots=True)
class ParsedPage:
    _mapping: PdfMapping
    _extractor: PdfTextExtractor

    @classmethod
    def from_object(cls, value: object) -> ParsedPage:
        page_mapping = mapping(value)
        if page_mapping is None or not isinstance(value, PdfTextExtractor):
            raise TypeError("PDF page does not provide the required read-only surface")
        return cls(page_mapping, value)

    def get(self, key: object, default: object = None, /) -> object:
        return self._mapping.get(key, default)

    def extract_text(self) -> str:
        return self._extractor.extract_text()


@dataclass(frozen=True, slots=True)
class ParsedPdf:
    is_encrypted: bool
    root_object: object | None
    pages: tuple[ParsedPage, ...]
    user_access_permissions: object
    permissions_valid: bool | None


def permission_validity(value: object) -> bool | None:
    if not isinstance(value, PdfPermissionValidity):
        return None
    validity = value.are_permissions_valid
    return validity if isinstance(validity, bool) else None


def resolve(value: object) -> object:
    if isinstance(value, PdfResolvable):
        resolved = value.get_object()
        return value if resolved is None else resolved
    return value


def mapping(value: object) -> PdfMapping | None:
    resolved = resolve(value)
    return resolved if isinstance(resolved, PdfMapping) else None


def array_items(value: object) -> Iterator[object]:
    resolved = resolve(value)
    if isinstance(resolved, (str, bytes, bytearray)) or not isinstance(
        resolved, PdfArray
    ):
        return
    for index in range(len(resolved)):
        yield resolved[index]
