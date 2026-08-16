"""Fail-closed HanDoc execution boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import NoReturn

from .adapters.base import Capability, CapabilityState
from .errors import DocumentError, DocumentErrorCode
from .handoc_child_process import (
    MAX_CAPTURE_BYTES,
    Cancellation,
    ProcessFactory,
    default_process_factory,
)

DESCRIPTOR_BOUND_EXECUTION_REASON = (
    "HanDoc descriptor-bound execution is unavailable: the isolation runner, "
    "Node executable, tool, and complete module tree cannot all be bound to "
    "verified open descriptors through child launch on every supported platform"
)


def _error(code: DocumentErrorCode, message: str) -> DocumentError:
    return DocumentError(code, "render", message)


def execute_handoc(
    config: Mapping[str, object],
    arguments: Sequence[str],
    *,
    capability: Callable[[], Capability],
    required_packages: Mapping[str, str],
    timeout: float,
    process_factory: ProcessFactory,
    cancellation: Cancellation | None,
) -> NoReturn:
    """Refuse launch until every executable input can remain descriptor-bound."""
    _ = config, arguments, required_packages, timeout, process_factory
    if cancellation is not None and cancellation.cancelled:
        raise _error(DocumentErrorCode.RENDER_FAILED, "HanDoc process cancelled")
    available = capability()
    reason = (
        available.reason
        if available.state is not CapabilityState.AVAILABLE
        else DESCRIPTOR_BOUND_EXECUTION_REASON
    )
    raise _error(DocumentErrorCode.CAPABILITY_UNAVAILABLE, reason)


__all__ = [
    "DESCRIPTOR_BOUND_EXECUTION_REASON",
    "MAX_CAPTURE_BYTES",
    "Cancellation",
    "ProcessFactory",
    "default_process_factory",
    "execute_handoc",
]
