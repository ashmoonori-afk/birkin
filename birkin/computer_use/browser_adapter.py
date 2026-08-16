"""Optional typed browser-page adapter boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .backends.base import BackendError


@dataclass(frozen=True, slots=True)
class BrowserBindingProof:
    session_id: str
    backend_id: str
    pid: int
    process_generation: str
    native_window_id: str
    window_generation: int
    page_target_id: str
    page_generation: int
    mutation_allowed: bool


class BrowserPageAdapter(Protocol):
    """Page-only seam; browser chrome and OS surfaces remain native."""

    def binding_proof(self) -> BrowserBindingProof: ...

    def capture_page(self, proof: BrowserBindingProof) -> object: ...

    def mutate_page(
        self,
        proof: BrowserBindingProof,
        action: object,
    ) -> object: ...


def validate_browser_route(
    proof: BrowserBindingProof,
    *,
    session_id: str,
    pid: int,
    process_generation: str,
    native_window_id: str,
    window_generation: int,
    mutation: bool,
) -> BrowserBindingProof:
    expected = (
        session_id,
        pid,
        process_generation,
        native_window_id,
        window_generation,
    )
    observed = (
        proof.session_id,
        proof.pid,
        proof.process_generation,
        proof.native_window_id,
        proof.window_generation,
    )
    if observed != expected:
        raise BackendError(
            "identity_mismatch",
            "The browser page proof does not match the native target.",
        )
    if mutation and not proof.mutation_allowed:
        raise BackendError(
            "browser_mutation_not_allowed",
            "The browser adapter did not grant page mutation authority.",
        )
    return proof
