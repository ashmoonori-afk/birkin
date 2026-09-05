"""Deterministic publication surfaces derived from the adapter catalog."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TypedDict

from .provenance_models import AdapterInventory, PackageInventory

CATALOG_REVISION = 7
NOTICE_PATH = Path(__file__).with_name("THIRD_PARTY_NOTICES.md")
MANIFEST_PATH = Path(__file__).with_name("provenance_manifest.json")


class ProvenanceManifest(TypedDict):
    schema: str
    catalog_revision: int
    inventory_sha256: str
    inventory: list[AdapterInventory]


def _canonical_inventory(inventory: list[AdapterInventory]) -> bytes:
    return json.dumps(
        inventory,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def provenance_manifest() -> ProvenanceManifest:
    """Build the machine publication directly from the typed catalog."""
    # Import at projection time so publications always use the authoritative API.
    from .catalog import adapter_inventory

    inventory = adapter_inventory()
    return {
        "schema": "https://birkin.invalid/schemas/office-adapter-provenance-v1",
        "catalog_revision": CATALOG_REVISION,
        "inventory_sha256": hashlib.sha256(_canonical_inventory(inventory)).hexdigest(),
        "inventory": inventory,
    }


def manifest_json() -> str:
    return (
        json.dumps(provenance_manifest(), ensure_ascii=True, indent=2, sort_keys=True)
        + "\n"
    )


def _unique_packages(inventory: list[AdapterInventory]) -> list[PackageInventory]:
    packages: dict[str, PackageInventory] = {}
    for adapter in inventory:
        for package in adapter["packages"]:
            previous = packages.setdefault(package["name"], package)
            if previous != package:
                raise ValueError(f"conflicting provenance for {package['name']}")
    return [packages[name] for name in sorted(packages, key=str.casefold)]


def _evidence(label: str, value: str | None) -> str:
    return f"- {label}: {value if value is not None else 'not proven'}"


def render_third_party_notices() -> str:
    """Render the human notice from the same package records as the manifest."""
    manifest = provenance_manifest()
    lines = [
        "# Office adapter third-party provenance",
        "",
        "This file is generated from `birkin.office.adapters.catalog`. Packages are",
        "optional or refused candidates; none is bundled or unconditionally selected.",
        "Operation capability comes from the inventory, not package discovery alone.",
        "",
        f"Catalog revision: {manifest['catalog_revision']}",
        f"Inventory SHA-256: `{manifest['inventory_sha256']}`",
        "",
    ]
    for package in _unique_packages(manifest["inventory"]):
        lines.extend(
            [
                f"## {package['name']}",
                "",
                f"- Publication: {package['publication_status']}",
                f"- Decision: {package['selection']}",
                f"- Integration: {package['integration_mode']}",
                _evidence("Exact version", package["version"]),
                _evidence("Approved range", package["version_range"]),
                _evidence("Repository", package["repository_url"]),
                _evidence("Tag", package["tag"]),
                _evidence("Commit", package["commit"]),
                _evidence("Artifact", package["artifact_url"]),
                _evidence("Artifact SHA-256", package["artifact_sha256"]),
                _evidence("License expression", package["license"]),
                _evidence("License text SHA-256", package["license_sha256"]),
                f"- Runtime evidence: {package['runtime_evidence']}",
                f"- OS evidence: {package['os_evidence']}",
                f"- Install probe: `{package['install_probe']}`",
                f"- Update procedure: {package['update_procedure']}",
                _evidence("Refusal reason", package["refusal_reason"]),
                f"- Role: {package['role']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Format specifications and internal implementation",
            "",
            "Built-in inspection and lossless-surgical operations use Birkin's internal",
            "implementation. The machine manifest records each cited format specification,",
            "security limit, fidelity limit, operation state, and availability separately.",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "MANIFEST_PATH",
    "NOTICE_PATH",
    "manifest_json",
    "provenance_manifest",
    "render_third_party_notices",
]
