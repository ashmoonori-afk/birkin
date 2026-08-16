"""Typed contracts for safe ODF package inspection and conversion refusal."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, TypeAlias, cast

OdfFormat: TypeAlias = Literal["odt", "ods", "odp"]
OdfRole: TypeAlias = Literal[
    "root", "core", "media", "embedded_object", "signature", "macro",
    "script", "encrypted", "directory", "unknown",
]
OdfSecurityKind: TypeAlias = Literal[
    "embedded_object", "signature", "macro", "script", "external_link", "encryption",
]
OdfStatus: TypeAlias = Literal["converter_unavailable", "refused"]

APPROVED_LIBREOFFICE_VERSION = "24.2.7.2"
APPROVED_LIBREOFFICE_FILTER_PAIRS = frozenset(
    {
        ("writer8", "Office Open XML Text"),
        ("writer8", "writer_pdf_Export"),
        ("calc8", "Calc MS Excel 2007 XML"),
        ("calc8", "calc_pdf_Export"),
        ("impress8", "Impress MS PowerPoint 2007 XML"),
        ("impress8", "impress_pdf_Export"),
    }
)
ODF_LOSS_CATEGORIES = frozenset(
    {
        "style_layout", "metadata", "formulas", "media", "embedded_objects",
        "active_content", "external_links", "signatures", "encryption", "unknown_parts",
    }
)


@dataclass(frozen=True)
class OdfManifestEntry:
    full_path: str
    media_type: str
    version: str | None
    encrypted: bool
    role: OdfRole
    part_sha256: str | None


@dataclass(frozen=True)
class OdfSecurityFinding:
    kind: OdfSecurityKind
    part: str
    target: str | None = None


@dataclass(frozen=True)
class OdfPreflight:
    status: Literal["accepted"]
    format: OdfFormat
    source: Path
    source_sha256: str
    media_type: str
    manifest_sha256: str
    manifest_entries: tuple[OdfManifestEntry, ...]
    security_inventory: tuple[OdfSecurityFinding, ...]
    security_inventory_sha256: str
    prospective_loss_categories: tuple[str, ...]
    allowed_operations: tuple[Literal["inspect", "clone_exact", "convert"], ...] = (
        "inspect", "clone_exact", "convert",
    )
    native_edit_supported: Literal[False] = False
    native_create_supported: Literal[False] = False

    def to_dict(self) -> dict[str, object]:
        return cast("dict[str, object]", asdict(self))


@dataclass(frozen=True)
class OdfCloneReceipt:
    source_sha256: str
    output_sha256: str
    manifest_sha256: str
    exact_byte_clone: Literal[True] = True
    native_edit_performed: Literal[False] = False
    native_create_performed: Literal[False] = False


@dataclass(frozen=True)
class OdfSandboxPolicy:
    network: Literal["offline"] = "offline"
    max_jobs: Literal[1] = 1
    source_read_only: Literal[True] = True
    jailed_temporary_directory: Literal[True] = True
    macros_enabled: Literal[False] = False
    scripts_enabled: Literal[False] = False
    external_updates_enabled: Literal[False] = False
    cpu_seconds: int = 30
    memory_bytes: int = 512 * 1024 * 1024
    output_bytes: int = 128 * 1024 * 1024
    timeout_seconds: int = 60
    process_tree_cleanup: Literal["kill_and_reap"] = "kill_and_reap"

    def __post_init__(self) -> None:
        fixed = (
            self.network == "offline",
            self.max_jobs == 1,
            self.source_read_only is True,
            self.jailed_temporary_directory is True,
            self.macros_enabled is False,
            self.scripts_enabled is False,
            self.external_updates_enabled is False,
            self.process_tree_cleanup == "kill_and_reap",
        )
        if not all(fixed):
            raise ValueError("ODF conversion requires the approved offline jailed policy")
        if min(self.cpu_seconds, self.memory_bytes, self.output_bytes, self.timeout_seconds) <= 0:
            raise ValueError("sandbox limits must be positive")


@dataclass(frozen=True)
class OdfLibreOfficePin:
    version: str
    input_filter: str
    output_filter: str
    engine: Literal["libreoffice"] = "libreoffice"

    def __post_init__(self) -> None:
        if self.engine != "libreoffice":
            raise ValueError("only the approved LibreOffice engine is supported")
        if self.version != APPROVED_LIBREOFFICE_VERSION:
            raise ValueError("LibreOffice version is not the exact approved version")
        if (self.input_filter, self.output_filter) not in APPROVED_LIBREOFFICE_FILTER_PAIRS:
            raise ValueError("LibreOffice filters are not an exact approved pair")


@dataclass(frozen=True)
class OdfLossBudget:
    accepted_categories: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(set(self.accepted_categories)) != len(self.accepted_categories):
            raise ValueError("loss budget contains duplicate categories")
        unknown = set(self.accepted_categories) - ODF_LOSS_CATEGORIES
        if unknown:
            raise ValueError(f"loss budget contains unknown categories: {sorted(unknown)}")


@dataclass(frozen=True)
class OdfManifestSecurityConsent:
    source_sha256: str
    manifest_sha256: str
    security_inventory_sha256: str
    mode: Literal["conversion_loss_accepted"] = "conversion_loss_accepted"

    def __post_init__(self) -> None:
        if self.mode != "conversion_loss_accepted":
            raise ValueError("manifest/security consent mode is not approved")
        values = (self.source_sha256, self.manifest_sha256, self.security_inventory_sha256)
        if any(len(value) != 64 or any(char not in "0123456789abcdef" for char in value) for value in values):
            raise ValueError("manifest/security consent requires lowercase SHA-256 values")


@dataclass(frozen=True)
class OdfConversionRequest:
    target_format: str
    source_sha256: str
    engine: OdfLibreOfficePin
    loss_budget: OdfLossBudget
    consent: OdfManifestSecurityConsent
    policy: OdfSandboxPolicy = field(default_factory=OdfSandboxPolicy)

    def __post_init__(self) -> None:
        if not self.target_format or self.target_format.startswith(".") or self.target_format.lower() != self.target_format:
            raise ValueError("target_format must be a lowercase bare format name")
        if len(self.source_sha256) != 64 or any(char not in "0123456789abcdef" for char in self.source_sha256):
            raise ValueError("source_sha256 must be a lowercase SHA-256 value")


@dataclass(frozen=True)
class OdfConversionReceipt:
    status: OdfStatus
    reason_code: str
    reason: str
    source_sha256: str
    source_format: OdfFormat
    target_format: str
    engine: OdfLibreOfficePin
    policy: OdfSandboxPolicy
    prospective_loss_categories: tuple[str, ...]
    output: None = None

    def to_dict(self) -> dict[str, object]:
        return cast("dict[str, object]", asdict(self))


class OdfConversionRefusal(ValueError):
    receipt: OdfConversionReceipt

    def __init__(self, receipt: OdfConversionReceipt) -> None:
        self.receipt = receipt
        super().__init__(receipt.reason)
