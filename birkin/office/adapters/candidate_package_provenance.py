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


def _handoc(name: str, role: str) -> PackageRecord:
    return PackageRecord(
        name=name,
        publication_status=PublicationStatus.UNPUBLISHED,
        integration_mode=IntegrationMode.CONDITIONAL_SOURCE_BUILD,
        selection=SelectionDecision.REFUSE,
        version=None,
        version_range=None,
        repository_url="https://github.com/muin-company/handoc",
        tag=None,
        commit=None,
        artifact_url=None,
        artifact_sha256=None,
        license=None,
        license_sha256=None,
        runtime_evidence=(
            "Proposed Node.js 22.14.0 x64 runtime; source revision is unproven."
        ),
        os_evidence="x64 was proposed; no verified OS support matrix is recorded.",
        install_probe="source-provenance-required:commit+artifact+license-hash",
        update_procedure=(
            "Approve an immutable source revision and artifact with license evidence, "
            "then regenerate the manifest and notices."
        ),
        refusal_reason=(
            "No npm publication, approved commit, source artifact hash, or license "
            "hash is proven."
        ),
        role=role,
    )


HANDOC_PARSER = _handoc(
    "@handoc/hwpx-parser", "Unpublished HWPX parser workspace candidate."
)
HANDOC_WRITER = _handoc(
    "@handoc/hwpx-writer", "Unpublished HWPX writer workspace candidate."
)
