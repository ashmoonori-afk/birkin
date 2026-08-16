"""Typed payloads shared by document service operations."""

from __future__ import annotations

from typing import Literal, TypedDict


class ArtifactRef(TypedDict):
    artifact_id: str
    content_hash: str
    media_type: str
    uri: str
    sensitivity: str
    acl_fingerprint: str


class CreationEvidence(TypedDict):
    check: str
    passed: bool
    detail: str


class CreationReceipt(TypedDict):
    operation: Literal["document_create"]
    version: int
    format: str
    creation_mode: Literal["blank_authoring", "template_derivation"]
    output_name: str
    source_sha256: str | None
    output_sha256: str


class CreatedDocument(TypedDict):
    status: Literal["draft"]
    draft_artifact: ArtifactRef
    format: str
    creation_mode: Literal["blank_authoring", "template_derivation"]
    source_sha256: str | None
    template_sha256: str | None
    output_sha256: str
    capability_limits: list[str]
    fidelity_limits: list[str]
    validation_evidence: list[CreationEvidence]
    warnings: list[str]
    receipt: CreationReceipt


class SourceIdentity(TypedDict):
    sha256: str
    locator: str


class ExtractedSpan(TypedDict):
    text: str
    source_sha256: str
    source_locator: dict[str, object]
    method: str


class ExtractedNode(TypedDict):
    id: str
    kind: str
    text: str
    order: int
    source_locator: dict[str, object]


class ExtractionLimits(TypedDict):
    max_spans: int
    max_nodes: int
    max_text_bytes: int


class Truncation(TypedDict):
    truncated: bool
    reasons: list[str]


class FeatureSupport(TypedDict):
    state: str
    reason: str


class ExtractionResult(TypedDict):
    source: SourceIdentity
    spans: list[ExtractedSpan]
    nodes: list[ExtractedNode]
    text: str
    projection: str
    limits: ExtractionLimits
    truncation: Truncation
    unsupported: dict[str, FeatureSupport]


class ExtractedItem(TypedDict):
    text: str
    kind: str
    locator: dict[str, object]
    method: str


class ConversionEngine(TypedDict):
    name: str
    version: str
    adapter: str
    adapter_version: str
    adapter_standard: str
    provenance: dict[str, int | str]


class ConversionObservation(TypedDict):
    category: str
    status: str
    observed: int
    budget: int


class ConversionPreservation(TypedDict):
    category: str
    status: str
    spans: int


class ConversionObserved(TypedDict):
    preservation: list[ConversionPreservation]
    loss: list[ConversionObservation]
    warnings: list[str]


class ConversionReceipt(TypedDict):
    operation: Literal["document_convert"]
    version: int
    source_sha256: str
    output_sha256: str
    engine: ConversionEngine
    route: dict[str, str]
    options: dict[str, str | bool]
    loss_budget: dict[str, int]
    observed: ConversionObserved
    sandbox: dict[str, bool]
    validation: dict[str, bool | list[str]]
    diff: dict[str, bool | int]
    preview: dict[str, str | bool]
    limits: dict[str, int]


class ConvertedDocument(TypedDict):
    status: Literal["draft"]
    draft_artifact: ArtifactRef
    source_sha256: str
    output_sha256: str
    source_format: str
    target_format: Literal["txt"]
    receipt: ConversionReceipt
