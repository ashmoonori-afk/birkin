from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol


class CapabilityState(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    READ_ONLY = "read_only"


class OperationState(str, Enum):
    NATIVE = "native"
    LOSSLESS_SURGICAL = "lossless-surgical"
    CONVERSION_ONLY = "conversion-only"
    READ_ONLY = "read-only"
    UNSUPPORTED = "unsupported"


class IntegrationMode(str, Enum):
    INTERNAL_STDLIB = "internal-stdlib"
    OPTIONAL_PYTHON = "optional-python"
    CONDITIONAL_SOURCE_BUILD = "conditional-source-build"
    NONE = "none"


class SelectionDecision(str, Enum):
    SELECT = "select"
    CONDITIONAL = "conditional"
    REFUSE = "refuse"


class PublicationStatus(str, Enum):
    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"


@dataclass(frozen=True, slots=True)
class Capability:
    state: CapabilityState
    reason: str
    install_hint: str | None = None


CAPABILITY_NAMES = (
    "inspect",
    "extract",
    "create",
    "compare",
    "fill",
    "patch",
    "render",
    "validate",
    "convert",
)


def default_capabilities(*, read_only: bool = False) -> dict[str, Capability]:
    result = {
        name: Capability(CapabilityState.AVAILABLE, "native package support")
        for name in CAPABILITY_NAMES
    }
    if read_only:
        for name in ("fill", "patch"):
            result[name] = Capability(
                CapabilityState.READ_ONLY,
                "format content mutation is intentionally unsupported",
            )
    for name in ("create", "render", "validate", "convert"):
        result[name] = Capability(
            CapabilityState.UNAVAILABLE,
            f"{name} engine is not configured",
        )
    return result


class DocumentAdapter(Protocol):
    format: str

    def capabilities(self) -> dict[str, Capability]: ...

    def inspect(self, path: Path) -> dict[str, object]: ...
