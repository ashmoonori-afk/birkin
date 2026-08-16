"""Optional format adapters; implementations import optional libraries lazily."""

from .adapter_provenance import provenance_manifest, render_third_party_notices
from .base import (
    Capability,
    CapabilityState,
    DocumentAdapter,
    IntegrationMode,
    OperationState,
    PublicationStatus,
    SelectionDecision,
)
from .catalog import AdapterInventory, adapter_inventory, supported_formats

__all__ = [
    "AdapterInventory",
    "Capability",
    "CapabilityState",
    "DocumentAdapter",
    "IntegrationMode",
    "OperationState",
    "PublicationStatus",
    "SelectionDecision",
    "adapter_inventory",
    "provenance_manifest",
    "render_third_party_notices",
    "supported_formats",
]
