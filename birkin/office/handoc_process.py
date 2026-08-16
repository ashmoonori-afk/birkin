"""Fail-closed configuration for isolated HanDoc execution."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import NoReturn, Protocol, final

from .adapters.base import Capability, CapabilityState
from .handoc_execution import (
    DESCRIPTOR_BOUND_EXECUTION_REASON,
    MAX_CAPTURE_BYTES,
    Cancellation,
    ProcessFactory,
    default_process_factory,
    execute_handoc,
)
from .handoc_identity import runtime_is_valid

REQUIRED_NODE_VERSION = "22.14.0"
REQUIRED_PACKAGES = {
    "@handoc/hwpx-parser": "0.1.0",
    "@handoc/hwpx-writer": "0.1.0",
}
ISOLATION_PROTOCOL = "birkin-handoc-isolation-v1"
HINT = (
    "HanDoc execution remains disabled until Birkin provides a descriptor-bound "
    "launcher for Node.js 22.14.0 x64, @handoc/hwpx-parser@0.1.0, "
    "@handoc/hwpx-writer@0.1.0, and the complete module tree."
)


class Runner(Protocol):
    """Legacy probe injection retained for API compatibility; probes are not run."""

    def __call__(
        self,
        args: Sequence[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: float,
        check: bool,
        env: Mapping[str, str],
    ) -> object: ...


@final
class HanDocProcess:
    def __init__(
        self,
        config: Mapping[str, object],
        *,
        runner: Runner | None = None,
        process_factory: ProcessFactory | None = None,
    ) -> None:
        self.config = config
        self.runner = runner  # compatibility only: direct runtime probes are unsafe
        self.process_factory = process_factory or default_process_factory()

    def _timeout(self) -> float:
        configured = self.config.get("timeout_seconds", 30)
        if (
            isinstance(configured, (int, float))
            and not isinstance(configured, bool)
            and math.isfinite(configured)
            and configured > 0
        ):
            return float(configured)
        return 30.0

    def capability(self) -> Capability:
        valid = (
            self.config.get("isolation_protocol") == ISOLATION_PROTOCOL
            and self.config.get("node_version") == REQUIRED_NODE_VERSION
            and runtime_is_valid(self.config, REQUIRED_PACKAGES)
        )
        if not valid:
            return Capability(
                CapabilityState.UNAVAILABLE,
                "HanDoc isolation runtime is not configured or identity-bound",
                HINT,
            )
        return Capability(
            CapabilityState.UNAVAILABLE,
            DESCRIPTOR_BOUND_EXECUTION_REASON,
            HINT,
        )

    def execute(
        self,
        arguments: Sequence[str],
        *,
        cancellation: Cancellation | None = None,
    ) -> NoReturn:
        return execute_handoc(
            self.config,
            arguments,
            capability=self.capability,
            required_packages=REQUIRED_PACKAGES,
            timeout=self._timeout(),
            process_factory=self.process_factory,
            cancellation=cancellation,
        )


__all__ = [
    "HINT",
    "ISOLATION_PROTOCOL",
    "MAX_CAPTURE_BYTES",
    "REQUIRED_NODE_VERSION",
    "REQUIRED_PACKAGES",
    "Cancellation",
    "HanDocProcess",
    "ProcessFactory",
    "Runner",
]
