"""Obsidian-vault memory compatibility surface.

Note I/O, retrieval/digests, formatting, and mutation locks live in cohesive
modules. This facade preserves the public exception, constants, class, and the
legacy helper seams exercised by the pinned package tests.
"""

from __future__ import annotations

from pathlib import Path

from . import frontmatter as frontmatter
from .index_config import ARCHIVE_ZONE as ARCHIVE_ZONE
from .index_config import IDENTITY_ZONE as IDENTITY_ZONE
from .index_config import TYPE_ZONE as TYPE_ZONE
from .index_config import WIKILINK_RE as WIKILINK_RE
from .memory_format import snippet as _snippet_impl
from .memory_io import MemoryConfig
from .memory_io import VALID_POLARITIES as VALID_POLARITIES
from .memory_io import VALID_TYPES as VALID_TYPES
from .memory_io import vault_dir as _vault_dir_impl
from .memory_retrieval import MemoryRetrieval as _MemoryRetrieval


class VersionMismatchError(ValueError):
    """Raised when an optimistic write version differs from on-disk state."""


def _vault_dir(cfg: MemoryConfig | None = None) -> Path:
    return _vault_dir_impl(cfg)


def _snippet(text: str, terms: list[str] | str, width: int = 240) -> str:
    return _snippet_impl(text, terms, width)


class VaultMemory(_MemoryRetrieval):
    """Ergonomic writes, retrieval, linking, placement, and prompt digests."""

    _version_error: type[ValueError] = VersionMismatchError

    def __init__(self, cfg: MemoryConfig | None = None) -> None:
        super().__init__(cfg)
