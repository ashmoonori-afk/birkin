"""Refused external candidates that do not establish adapter capability."""

from __future__ import annotations

from .base import IntegrationMode, PublicationStatus, SelectionDecision
from .provenance_models import PackageRecord

REPORTLAB = PackageRecord(
    name="ReportLab",
    publication_status=PublicationStatus.PUBLISHED,
    integration_mode=IntegrationMode.OPTIONAL_PYTHON,
    selection=SelectionDecision.REFUSE,
    version=None,
    version_range=None,
    repository_url="https://github.com/MrBitBucket/reportlab-mirror",
    tag=None,
    commit=None,
    artifact_url=None,
    artifact_sha256=None,
    license=None,
    license_sha256=None,
    runtime_evidence="No approved project dependency or lock artifact.",
    os_evidence="Not evaluated.",
    install_probe="approval-required:reportlab",
    update_procedure=(
        "Add an approved dependency range and lock artifact, verify license evidence, "
        "then regenerate the manifest and notices."
    ),
    refusal_reason=(
        "Not present in an approved dependency extra or the lock as a direct package."
    ),
    role="Refused PDF creation candidate; it does not establish a capability.",
)
