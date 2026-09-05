# Office Work OS v2

This shipped contract describes registered runtime behavior, not theoretical package features.

- Birkin version: `0.4.357`
- `catalog_revision: 4`
- `inventory_sha256: a49ab813ee4cdea3d6f87e0e2bd063b1dde54058e5c8dd0af0cf32bec74cae95`
- Machine publication: [`provenance_manifest.json`](../birkin/office/adapters/provenance_manifest.json)
- Generated evidence: [`THIRD_PARTY_NOTICES.md`](../birkin/office/adapters/THIRD_PARTY_NOTICES.md)

The tracked catalog and these generated package-tree files are the publication authority. No ignored `.omo` research file is required to interpret or verify support.

## Runtime support matrix

- `bounded`: a registered implementation covers only the stated subset.
- `conditional`: an approved lazy dependency may be required.
- `conditional`: an exact-pinned, local Python backend may be required.
- `structural`: validation reports independent layers and incomplete checks.
- `layered`: comparison independently reports byte, bounded semantic, package, and visual status.
- `structured-preview`: semantic preview succeeds; visual rendering remains unavailable.

<!-- office-support-matrix:start -->
| Format ID | Read/inspect | Create | Extract | Validate | Compare | Text convert | Surgical mutation | Render/recalc/forms |
|---|---|---|---|---|---|---|---|---|
| `docx` | bounded | conditional | bounded | structural | layered | bounded | bounded | structured-preview |
| `xlsx` | bounded | conditional | bounded | structural | layered | bounded | bounded | structured-preview |
| `pptx` | bounded | conditional | bounded | structural | layered | bounded | bounded | structured-preview |
| `pdf` | bounded | bounded | conditional | structural | layered | conditional | refused | structured-preview |
| `hwpx` | bounded | conditional | bounded | structural | layered | bounded | bounded | structured-preview |
<!-- office-support-matrix:end -->

### Format boundaries

| Format | Current bounded behavior | Explicit boundary |
|---|---|---|
| DOCX | Paragraph creation, package inspection/extraction, layered validation/comparison, TXT projection, and one tagged content-control edit. | No tracked-change synthesis, arbitrary rewrite, or layout proof. |
| XLSX | Scalar-row creation, cell extraction, layered validation/comparison, TXT projection, and one existing sheet-1 cell edit. | Formulas are preserved but never evaluated or recalculated. |
| PPTX | Title/body creation, text extraction, layered validation/comparison, TXT projection, and one slide-1 placeholder edit. | No master, animation, media, overflow, or layout proof. |
| PDF | Built-in ASCII text-first creation; optional pypdf inspection/extraction; structural validation and TXT projection. | Non-Latin creation returns a typed refusal. Existing content is read-only: no OCR, form fill, annotation, signing, redaction, or object rewrite. |
| HWPX | Exact-pinned `python-hwpx==6.1.0` text-first blank authoring, trusted-template field derivation, extraction, validation/comparison, TXT projection, and one section-0 field edit. | No legacy HWP, application automation, PDF export, or typography proof. |

Trusted Korean and English Office requests are routed before model execution from user intent and supplied artifact names only. DOCX, XLSX, PPTX, PDF, and HWPX select their matching bundled skill; general Office requests select `office-work-os`; conflicts select inspect-first `office-documents`. Extracted document text is never routing authority. All routed writes remain copy-on-write.

Korean format aliases are deterministic: `보고서` and `리포트` select DOCX,
`파워포인트` and `피피티` select PPTX, and `한글파일` selects HWPX. If one
request names more than one format, Birkin routes to `office-documents` and
asks exactly `어느 포맷으로 저장할까요?` before any mutation proposal.

## Registered tools and arguments

The exact registered set is `list_document_adapters`, `inspect_document`, `extract_document`, `compare_documents`, `render_artifact`, `validate_artifact`, `office_job_request`, and `office_rollback_request`.

| Tool | Required arguments | Important optional arguments/behavior |
|---|---|---|
| `list_document_adapters` | none | Returns the authoritative catalog. |
| `inspect_document` | `source` | Existing artifacts must be inspected first. |
| `extract_document` | `source` | `projection`, `max_spans`, `max_nodes`, `max_text_bytes`. |
| `compare_documents` | `left`, `right` | Returns separate byte, semantic, package, and visual claims. |
| `render_artifact` | `artifact` | `output_format` is `structured_preview`, `pdf`, `png`, or `thumbnail`; `page` is optional. |
| `validate_artifact` | `artifact` | Reports package, schema-root, formula, openability, security, and fidelity layers. |
| `office_job_request` | `request`, `outcome`, `destination`, plus either `format` + `content` or `source` + `operations` | Source-free DOCX creation queues `office_create`; existing-document mutation queues `office_job`. Only canonical approval execution may create, mutate, or export. |
| `office_rollback_request` | `job_id` | Queues a second high-risk approval for one HMAC-authenticated, unexpired export receipt. |

The seven synchronized skill IDs are `office-work-os`, `office-documents`, `word-documents`, `spreadsheets`, `presentations`, `pdf-documents`, and `korean-hwp-documents`. Their machine metadata requires the same eight-tool set.

## Workspace input jail

`BIRKIN_HOME/office` is the dedicated document workspace jail, separate from configuration, vault, session, and native bootstrap files. Every source and HWPX template URI must be an absolute regular file inside it and its bytes must match `content_hash`. For example, with `BIRKIN_HOME=/workspace/.birkin`, first copy or import inputs under `/workspace/.birkin/office/artifacts/incoming`. `/workspace/source.docx`, `/tmp/source.docx`, and symlink escapes are rejected.

The durable job journal remains at `BIRKIN_HOME/office/jobs`. A pending job created with a source outside the dedicated Office jail is not migrated or resumed: re-import the source into `BIRKIN_HOME/office` and submit a new approval proposal. This fail-closed rule prevents legacy source descriptors from reaching configuration or vault files.

Read-only inspection, extraction, comparison, validation, and structured preview do not create mutation authority. Generic model file tools cannot access Office receipt keys, durable jobs, validated drafts, export backups, transaction journals, or destination locks. Consequential mutation or export has one public entry point: `office_job_request`. Its destination must resolve beneath the caller's allowlisted root; mutation remains copy-on-write and publication is no-replace unless the exact approval authorizes overwrite. Rollback is never implicit: `office_rollback_request` creates a separate approval for the durable job. Signed receipts expire after 30 days; the next Office request purges expired active backup paths and transaction/job journals. Legacy unsigned receipts cannot authorize rollback. Authenticated helper and backup names are namespace-retired into a private `.birkin-retire` directory instead of being truncated or deleted by pathname. POSIX cannot safely erase those inode bytes while preserving a concurrently added hard link, so quarantined bytes may remain; they are excluded from active state and cannot authorize rollback.

Inspect and extract inside the jail:

```text
inspect_document
{"source":{"content_hash":"<sha256>","uri":"/workspace/.birkin/office/artifacts/incoming/source.docx"}}

extract_document
{"source":{"content_hash":"<sha256>","uri":"/workspace/.birkin/office/artifacts/incoming/source.docx"},"projection":"text","max_spans":1000,"max_nodes":1000,"max_text_bytes":100000}
```

Request a mutation through the canonical coordinator:

```json
{
  "request": "Update cell A1 in this Excel workbook",
  "source": {"content_hash": "<sha256>", "uri": "/workspace/.birkin/office/artifacts/incoming/source.xlsx"},
  "outcome": "Set Revenue A1 to 9",
  "operations": [{"cell": "A1", "value": 9}],
  "destination": "/workspace/exports/approved.xlsx"
}
```

The request first inspects the exact source, builds a structured preview and semantic operation summaries, and binds the source hash, proposal digest, destination, exact operations, overwrite decision, and proposer in an `authority_digest`. It persists the job and creates a standard `office_job` approval record; the approving principal is recorded separately when that record is resolved. Requesting the job does not mutate the source or destination.

Only an executing claim from the canonical approval queue may resume that exact payload. Recovery restores the journaled job under its process lock, rechecks the queue payload, proposal and source digests, then executes, validates, publishes, exports, and returns the durable receipt. Changed authority or source bytes fail closed; rejected, failed, rolled-back, or otherwise non-resumable states are not silently retried.

Backend creation, conversion, and narrow patch capabilities remain bounded by the matrix above, but they are not separate public mutation authorities. Conversion requires an explicit `loss_budget` wherever the selected backend can lose document structure or fidelity. Active content and signed/encrypted sources remain refused where required; TXT remains a deterministic bounded projection, never native or lossless conversion.

## Comparison, validation, and rendering

`compare_documents` is not byte-only. It always reports hashes and byte equality, attempts normalized semantic comparison under node/text limits, and compares ZIP package entries, relationships, content types, and XML for package formats. PDF package comparison is explicitly unavailable. Visual comparison is always a separate unavailable result; semantic equality never aliases visual equality.

`validate_artifact` reports each attempted, unsupported, and not-run layer. Structural validity does not establish full conformance, accessibility, signature trust, recalculated formulas, openability in a desktop suite, or rendered fidelity.

A semantic preview succeeds as follows:

```text
render_artifact
{"artifact":{"content_hash":"<sha256>","uri":"/workspace/.birkin/office/artifacts/incoming/source.docx"},"output_format":"structured_preview"}
```

The result has `render_kind: "structured_preview"`, `evidence_class: "semantic_preview"`, and `visual_proof: false`. Requests for `pdf`, `png`, or `thumbnail` return `RENDER_UNAVAILABLE`; this visual refusal must not be reported for a successful structured preview.

## Dependencies and provenance

Install `office` for approved OOXML lazy backends and `office-advanced` for optional pypdf inspection/extraction/deep reopen:

```bash
python -m pip install ".[office]"
python -m pip install ".[office-advanced]"
```

Missing optional Python backends return typed capability errors with installation evidence. Package discovery never upgrades capability by itself. ReportLab remains a refused provenance record and has no runtime execution or install-hint path; pypdfium2 remains unwired and does not enable visual rendering. Separately installed applications, executables, daemons, runtimes, and subprocess conversion engines are never discovered or launched. Exact package versions, source artifacts, hashes, licenses, probes, and refusal reasons are in the tracked manifest and notice files linked above.

## Security and resource boundaries

Package preflight bounds ZIP entries, expanded bytes, compression ratios, XML bytes/nodes/depth/attributes/text, media, and embedded package depth. It rejects absolute, traversal, noncanonical, duplicate, special, encrypted, malformed, entity-bearing, or over-limit entries. External relationships and active content are inventory findings, never permission to follow or execute them.

Macros, formulas, PDF actions, links, embedded objects, comments, metadata, and document prose are untrusted data. Encryption detection is not decryption. Signature presence is not certificate, revocation, timestamp, or policy verification, and mutation may invalidate signatures.
