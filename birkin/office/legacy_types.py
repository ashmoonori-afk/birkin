"""Typed contracts for isolated legacy document handling."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, TypeAlias, cast

LegacyFormat: TypeAlias = Literal["doc", "xls", "ppt", "rtf"]
LegacyStatus: TypeAlias = Literal["accepted", "refused", "converter_unavailable"]


@dataclass(frozen=True)
class LegacyLimits:
    """Bounds applied before any converter is considered."""

    max_input_bytes: int = 64 * 1024 * 1024
    max_cfb_sectors: int = 131_072
    max_cfb_directory_entries: int = 16_384
    max_rtf_controls: int = 100_000


@dataclass(frozen=True)
class LegacySandboxPolicy:
    """Non-negotiable process isolation contract for one conversion job."""

    network: Literal["offline"] = "offline"
    max_jobs: Literal[1] = 1
    source_read_only: Literal[True] = True
    jailed_temporary_directory: Literal[True] = True
    cpu_seconds: int = 30
    memory_bytes: int = 512 * 1024 * 1024
    output_bytes: int = 128 * 1024 * 1024
    timeout_seconds: int = 60
    process_tree_cleanup: Literal["kill_and_reap"] = "kill_and_reap"
    macros_enabled: Literal[False] = False
    scripts_enabled: Literal[False] = False
    ole_activation_enabled: Literal[False] = False
    external_updates_enabled: Literal[False] = False

    def __post_init__(self) -> None:
        if min(self.cpu_seconds, self.memory_bytes, self.output_bytes, self.timeout_seconds) <= 0:
            raise ValueError("sandbox limits must be positive")


@dataclass(frozen=True)
class LegacyEnginePin:
    """An exact converter and import/export filter selection."""

    engine: Literal["libreoffice", "pandoc", "unoconv"]
    version: str
    input_filter: str
    output_filter: str

    def __post_init__(self) -> None:
        values = (self.version, self.input_filter, self.output_filter)
        if any(not value.strip() for value in values):
            raise ValueError("engine version and filters must be non-empty exact pins")
        if any(marker in self.version.lower() for marker in ("*", "latest", ">", "<", "~", "^")):
            raise ValueError("engine version must be exact")


@dataclass(frozen=True)
class LegacyConversionRequest:
    target_format: str
    engine: LegacyEnginePin
    policy: LegacySandboxPolicy = field(default_factory=LegacySandboxPolicy)

    def __post_init__(self) -> None:
        if not self.target_format or self.target_format.startswith("."):
            raise ValueError("target_format must be a bare, non-empty format name")


@dataclass(frozen=True)
class LegacyPreflight:
    status: Literal["accepted"]
    format: LegacyFormat
    source: Path
    source_sha256: str
    size_bytes: int
    container: Literal["cfb", "rtf"]
    inventory: tuple[str, ...]
    encoding: str | None
    prospective_loss_categories: tuple[str, ...]
    allowed_operations: tuple[Literal["read_extract", "convert"], ...] = (
        "read_extract",
        "convert",
    )
    native_edit_supported: Literal[False] = False
    native_create_supported: Literal[False] = False

    def to_dict(self) -> dict[str, object]:
        return cast("dict[str, object]", asdict(self))


@dataclass(frozen=True)
class LegacyReceipt:
    status: LegacyStatus
    source_sha256: str
    source_format: str | None
    target_format: str | None
    prospective_loss_categories: tuple[str, ...]
    reason_code: str | None
    reason: str | None
    engine: LegacyEnginePin | None
    policy: LegacySandboxPolicy | None
    output: None = None

    def to_dict(self) -> dict[str, object]:
        return cast("dict[str, object]", asdict(self))


class LegacyRefusal(ValueError):
    """Typed refusal carrying a serializable, hash-bound receipt."""

    receipt: LegacyReceipt

    def __init__(self, receipt: LegacyReceipt) -> None:
        self.receipt = receipt
        super().__init__(receipt.reason or receipt.reason_code or "legacy input refused")
