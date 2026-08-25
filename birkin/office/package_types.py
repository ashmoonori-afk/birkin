"""Typed inventories shared by Office package scanning and cloning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from .limits import PackageLimits as BasePackageLimits


@dataclass(frozen=True)
class PackageLimits(BasePackageLimits):
    """Resource policy enforced before package content is trusted."""

    max_xml_bytes: int = 10_000_000
    max_xml_nodes: int = 1_000_000
    max_xml_depth: int = 256
    max_xml_attributes: int = 1_000_000
    max_xml_text_bytes: int = 10_000_000
    max_total_xml_bytes: int = 50_000_000
    max_total_xml_nodes: int = 2_000_000
    max_total_xml_text_bytes: int = 50_000_000
    max_media_bytes: int = 100_000_000
    allowed_media_types: tuple[str, ...] | None = None
    max_media_width: int | None = None
    max_media_height: int | None = None
    max_media_pixels: int | None = None
    max_media_frames: int | None = None
    max_package_depth: int = 0


DEFAULT_LIMITS = PackageLimits()


class ScannedPartManifest(TypedDict):
    index: int
    original_sha256: str
    compress_type: int
    date_time: tuple[int, int, int, int, int, int]
    external_attr: int
    create_system: int
    header_offset: int


class PartManifest(ScannedPartManifest):
    bytes: bytes


class ExternalRelationship(TypedDict):
    part_uri: str
    relationship_id: str
    target: str


class ActiveContent(TypedDict):
    part_uri: str
    kind: str


class PackageManifest(TypedDict):
    parts: dict[str, PartManifest]
    source_sha256: str
    external_relationships: list[ExternalRelationship]
    active_content: list[ActiveContent]


class PackageScanManifest(TypedDict):
    parts: dict[str, ScannedPartManifest]
    external_relationships: list[ExternalRelationship]
    active_content: list[ActiveContent]
