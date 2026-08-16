"""Typed contracts for binary HWP identity and security gating."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, TypeAlias, cast

HwpOperation: TypeAlias = Literal[
    "inspect", "read", "extract", "convert", "edit", "create", "render"
]
HwpCapabilityState: TypeAlias = Literal["available", "refused", "unavailable"]


@dataclass(frozen=True, slots=True)
class HwpLimits:
    """Hard bounds applied before any HWP content stream is interpreted."""

    max_input_bytes: int = 64 * 1024 * 1024
    max_cfb_sectors: int = 131_072
    max_directory_entries: int = 16_384
    max_chain_sectors: int = 131_072
    max_file_header_bytes: int = 4_096

    def __post_init__(self) -> None:
        if (
            min(
                self.max_input_bytes,
                self.max_cfb_sectors,
                self.max_directory_entries,
                self.max_chain_sectors,
                self.max_file_header_bytes,
            )
            <= 0
        ):
            raise ValueError("HWP limits must be positive")


@dataclass(frozen=True, slots=True)
class HwpRequiredTool:
    name: str
    status: Literal["unavailable"] = "unavailable"
    approved: Literal[False] = False
    provenance_requirement: str = "exact-name+version+artifact-hash+license"

    def to_dict(self) -> dict[str, object]:
        return cast("dict[str, object]", asdict(self))


@dataclass(frozen=True, slots=True)
class HwpCapability:
    operation: HwpOperation
    state: HwpCapabilityState
    reason_code: str
    reason: str
    flag_evidence: tuple[str, ...]
    required_tool: HwpRequiredTool | None

    def to_dict(self) -> dict[str, object]:
        return cast("dict[str, object]", asdict(self))


class HwpRefusal(ValueError):
    """A hash-bound identity or capability refusal with no output artifact."""

    receipt: dict[str, object]

    def __init__(
        self,
        *,
        operation: str,
        source_sha256: str,
        reason_code: str,
        reason: str,
        required_tool: HwpRequiredTool | None = None,
    ) -> None:
        self.receipt = {
            "status": "refused",
            "operation": operation,
            "source_sha256": source_sha256,
            "reason_code": reason_code,
            "reason": reason,
            "required_tool": required_tool.to_dict() if required_tool else None,
            "output": None,
        }
        super().__init__(reason)
