"""Authoritative typed Office adapter inventory API.

Stable provenance modules own immutable evidence by responsibility. This module
is the single projection boundary consumed by services and publications.
"""

from __future__ import annotations

from .adapter_record_provenance import ADAPTER_RECORDS
from .provenance_models import (
    AdapterInventory,
    CapabilityInventory,
    OperationRecord,
    PackageInventory,
    PackageRecord,
)


def _operation_payload(operation: OperationRecord) -> CapabilityInventory:
    return {
        "state": operation.state.value,
        "availability": operation.availability,
        "reason": operation.reason,
        "integration_mode": operation.integration_mode.value,
        "security_limits": operation.security_limits,
        "fidelity_limits": operation.fidelity_limits,
        "install_probe": operation.install_probe,
        "refusal_reason": operation.refusal_reason,
    }


def _package_payload(package: PackageRecord) -> PackageInventory:
    return {
        "name": package.name,
        "publication_status": package.publication_status.value,
        "integration_mode": package.integration_mode.value,
        "selection": package.selection.value,
        "version": package.version,
        "version_range": package.version_range,
        "repository_url": package.repository_url,
        "tag": package.tag,
        "commit": package.commit,
        "artifact_url": package.artifact_url,
        "artifact_sha256": package.artifact_sha256,
        "license": package.license,
        "license_sha256": package.license_sha256,
        "runtime_evidence": package.runtime_evidence,
        "os_evidence": package.os_evidence,
        "install_probe": package.install_probe,
        "update_procedure": package.update_procedure,
        "refusal_reason": package.refusal_reason,
        "role": package.role,
    }


def supported_formats(operation: str | None = None) -> tuple[str, ...]:
    """Return catalog formats, optionally limited to a supported operation."""
    if operation is None:
        return tuple(record.format for record in ADAPTER_RECORDS)
    return tuple(
        record.format
        for record in ADAPTER_RECORDS
        if (capability := dict(record.capabilities).get(operation)) is not None
        and capability.state.value != "unsupported"
    )


def adapter_inventory() -> list[AdapterInventory]:
    """Return a fresh JSON-compatible projection of the frozen catalog."""
    inventory: list[AdapterInventory] = []
    for record in ADAPTER_RECORDS:
        fidelity_limits = list(record.fidelity_limits)
        inventory.append(
            {
                "format": record.format,
                "standard_url": record.standard_url,
                "packages": [_package_payload(package) for package in record.packages],
                "capabilities": {
                    name: _operation_payload(operation)
                    for name, operation in record.capabilities
                },
                "security_limits": list(record.security_limits),
                "fidelity_limits": fidelity_limits,
                "limitations": fidelity_limits,
            }
        )
    return inventory


__all__ = [
    "AdapterInventory",
    "CapabilityInventory",
    "PackageInventory",
    "adapter_inventory",
    "supported_formats",
]
