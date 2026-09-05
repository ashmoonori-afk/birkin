"""Immutable typed records used by the Office adapter provenance catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from .base import (
    IntegrationMode,
    OperationState,
    PublicationStatus,
    SelectionDecision,
)


class CapabilityInventory(TypedDict):
    state: str
    availability: str
    reason: str
    integration_mode: str
    security_limits: str
    fidelity_limits: str
    install_probe: str | None
    refusal_reason: str | None
    public_entrypoint: str | None


class PackageInventory(TypedDict):
    name: str
    publication_status: str
    integration_mode: str
    selection: str
    version: str | None
    version_range: str | None
    repository_url: str
    tag: str | None
    commit: str | None
    artifact_url: str | None
    artifact_sha256: str | None
    license: str | None
    license_sha256: str | None
    runtime_evidence: str
    os_evidence: str
    install_probe: str
    update_procedure: str
    refusal_reason: str | None
    role: str


class AdapterInventory(TypedDict):
    format: str
    standard_url: str
    packages: list[PackageInventory]
    capabilities: dict[str, CapabilityInventory]
    security_limits: list[str]
    fidelity_limits: list[str]
    limitations: list[str]


@dataclass(frozen=True, slots=True)
class OperationRecord:
    state: OperationState
    availability: str
    reason: str
    integration_mode: IntegrationMode
    security_limits: str
    fidelity_limits: str
    install_probe: str | None = None
    refusal_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PackageRecord:
    name: str
    publication_status: PublicationStatus
    integration_mode: IntegrationMode
    selection: SelectionDecision
    version: str | None
    version_range: str | None
    repository_url: str
    tag: str | None
    commit: str | None
    artifact_url: str | None
    artifact_sha256: str | None
    license: str | None
    license_sha256: str | None
    runtime_evidence: str
    os_evidence: str
    install_probe: str
    update_procedure: str
    refusal_reason: str | None
    role: str


@dataclass(frozen=True, slots=True)
class AdapterRecord:
    format: str
    standard_url: str
    packages: tuple[PackageRecord, ...]
    capabilities: tuple[tuple[str, OperationRecord], ...]
    security_limits: tuple[str, ...]
    fidelity_limits: tuple[str, ...]
