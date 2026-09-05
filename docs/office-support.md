# Office Work OS v2

This shipped contract describes registered runtime behavior, not theoretical package features.

- Birkin version: `0.4.392`
- `catalog_revision: 8`
- `inventory_sha256: 54bb5a00d5370a69ec1c12e7e27ba72af51cfb11eb45dab912ab4ec10a008fd8`
- Machine publication: [`provenance_manifest.json`](../birkin/office/adapters/provenance_manifest.json)
- Generated evidence: [`THIRD_PARTY_NOTICES.md`](../birkin/office/adapters/THIRD_PARTY_NOTICES.md)

The tracked catalog and these generated package-tree files are the publication authority. No ignored `.omo` research file is required to interpret or verify support.

## Runtime support matrix

- `bounded`: a registered implementation covers only the stated subset.
- `conditional`: an approved lazy dependency may be required.
- `conditional`: an exact-pinned, local Python backend may be required.
- `structural`: validation reports independent layers and incomplete checks.
- `layered`: comparison independently reports byte, bounded semantic, package, and visual status.
- `structured-preview`: semantic preview succeeds without claiming visual proof.
- `conditional-page-image`: PDF alone can render one bounded page to PNG or thumbnail.

<!-- office-support-matrix:start -->
| Format ID | Read/inspect | Create | Extract | Validate | Compare | Text convert | Surgical mutation | Render/recalc/forms |
|---|---|---|---|---|---|---|---|---|
| `docx` | bounded | conditional | bounded | structural | layered | bounded | bounded | structured-preview |
| `xlsx` | bounded | conditional | bounded | structural | layered | bounded | bounded | structured-preview |
| `pptx` | bounded | conditional | bounded | structural | layered | bounded | bounded | structured-preview |
| `pdf` | bounded | bounded | conditional | structural | layered | conditional | refused | conditional-page-image |
| `hwpx` | bounded | conditional | bounded | structural | layered | bounded | bounded | structured-preview |
<!-- office-support-matrix:end -->

The machine catalog records `public_entrypoint` separately from the adapter's
lower-level capability. Installing a package does not create an agent route.

| Format | Read | Create | Edit | Render | Recalculate |
|---|---|---|---|---|---|
| DOCX | `extract_document` | `office_job_request` | `office_job_request` | structured preview through `render_artifact` | unavailable |
| XLSX | `extract_document` | `office_job_request` | `office_job_request` | structured preview through `render_artifact` | unavailable |
| PPTX | `extract_document` | `office_job_request` | `office_job_request` | structured preview through `render_artifact` | unavailable |
| PDF | conditional `extract_document` | `office_job_request` | unavailable | structured preview plus conditional PNG/thumbnail through `render_artifact` | unavailable |
| HWPX | `extract_document` | `office_job_request` | `office_job_request` | structured preview through `render_artifact` | unavailable |

### Format boundaries

| Format | Current bounded behavior | Explicit boundary |
|---|---|---|
| DOCX | Paragraph creation plus approved weekly-report, meeting-notes, and work-proposal plans with a title, body, one table, and one bullet list; package inspection/extraction, layered validation/comparison, TXT projection, and atomic multi-paragraph or tagged content-control edits. | No tracked-change synthesis, arbitrary rewrite, or layout proof. Business templates record their definition version/hash and sources but remain visually unverified until rendered. |
| XLSX | Scalar-row creation, cell extraction, layered validation/comparison, TXT projection, and atomic numeric edits across named existing sheets. | Formulas are preserved but never evaluated or recalculated. |
| PPTX | Title/body creation, text extraction, layered validation/comparison, TXT projection, and atomic placeholder edits across explicit slide parts. | No master, animation, media, overflow, or layout proof. |
| PDF | Built-in ASCII creation plus optional ReportLab creation with an embedded hash-bound TrueType font; optional pypdf inspection/extraction; structural validation and TXT projection. | Existing content is read-only: no OCR, form fill, annotation, signing, redaction, or object rewrite. Visual layout remains unverified until raster validation. |
| HWPX | Exact-pinned `python-hwpx==6.1.0` text-first blank authoring, trusted-template field derivation (including the three approved business plans), extraction, validation/comparison, TXT projection, and one section-0 field edit. | Business-plan derivation rejects missing required inputs and any template field left unbound. It records the source template hash and does not claim layout fidelity before rendering. No legacy HWP, application automation, PDF export, or typography proof. |

Trusted Korean and English Office requests are routed before model execution from user intent and supplied artifact names only. DOCX, XLSX, PPTX, PDF, and HWPX select their matching bundled skill, while general Office requests select `office-work-os`. Source formats and the target format are separate route fields; an explicit save format wins over a generic document label, and a default DOCX result is marked as a changeable suggestion. Extracted document text is never routing authority. All routed writes remain copy-on-write.

Korean format aliases are deterministic: `보고서` and `리포트` suggest DOCX,
`파워포인트` and `피피티` select PPTX, and `한글파일` selects HWPX. Multiple
source formats are allowed. If one request asks for more than one output
format, Birkin routes to `office-documents` and asks exactly
`어느 포맷으로 저장할까요?` before any mutation proposal.

## Registered tools and arguments

The exact registered set is `list_document_adapters`, `inspect_document`, `extract_document`, `analyze_workbook`, `review_meeting_actions`, `list_work_items`, `work_item_request`, `search_office_sources`, `list_office_batches`, `office_batch_request`, `list_office_templates`, `office_template_request`, `resolve_office_template`, `compare_documents`, `render_artifact`, `validate_artifact`, `office_job_request`, and `office_rollback_request`.

| Tool | Required arguments | Important optional arguments/behavior |
|---|---|---|
| `list_document_adapters` | none | Returns the authoritative catalog. |
| `inspect_document` | `source` | Existing artifacts must be inspected first. |
| `extract_document` | `source` | `projection`, `max_spans`, `max_nodes`, `max_text_bytes`. |
| `analyze_workbook` | `source`, `sheet`, `cell_range` | Optional `group_by`, `value_column`, `compare_by`, and `include_hidden_rows`; returns type/blank/duplicate checks, cell-linked aggregates, formula-cache status, and DOCX-ready report content without recalculation. |
| `review_meeting_actions` | `notes`, `candidates` | Requires exact source evidence, preserves unknown owner/due date, separates suggested dates, deduplicates, and returns an unpersisted confirmation draft. |
| `list_work_items` | none | Optional `timezone_name`; groups durable all-day items into today, overdue, missing owner/date, and recent completion. |
| `work_item_request` | `action` | Approval-gated create, meeting confirmation, update, or completion with conversation/document/goal/job source links. |
| `search_office_sources` | `query`, `sources` | Searches only live, access-granted current-work, selected-folder, or allowed-connection artifacts and returns exact extraction locators and versions. |
| `list_office_batches` | none | Lists per-file success and failure results without collapsing partial failure. |
| `office_batch_request` | `items` or `retry_batch_id` | Approval-binds up to 25 unique targets for sequential canonical Office jobs; retry plans include failed files only. |
| `list_office_templates` | none | Previews verified bases and saved versions visible to this workspace. |
| `office_template_request` | `action` | Approval-gates clone, rename, structural preference update, and default restore; body text is rejected. |
| `resolve_office_template` | `template_id`, `version`, `values` | Resolves one exact saved version into a verified built-in business-template input. |
| `compare_documents` | `left`, `right` | Returns separate byte, semantic, package, and visual claims. |
| `render_artifact` | `artifact` | `output_format` is `structured_preview`, `pdf`, `png`, or `thumbnail`; `page` is optional. |
| `validate_artifact` | `artifact` | Reports package, schema-root, formula, openability, security, and fidelity layers. |
| `office_job_request` | `request`, `outcome`, `destination`, plus either `format` + `content` or `source` + `operations` | Source-free DOCX/XLSX/PPTX/PDF/HWPX creation queues `office_create`; existing-document mutation queues `office_job`. Only canonical approval execution may create, mutate, or export. |
| `office_rollback_request` | `job_id` | Queues a second high-risk approval for one HMAC-authenticated, unexpired export receipt. |

The seven synchronized skill IDs are `office-work-os`, `office-documents`, `word-documents`, `spreadsheets`, `presentations`, `pdf-documents`, and `korean-hwp-documents`. Their machine metadata requires the same nine-tool set.

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

The semantic result has `render_kind: "structured_preview"`, `evidence_class: "semantic_preview"`, and `visual_proof: false`. For PDF only, PNG and thumbnail requests return one managed page image with source hash, renderer version, font resources, page count, render settings, blank-page status, and edge-contact evidence. PDF output and other formats' visual requests return `RENDER_UNAVAILABLE`.

## Dependencies and provenance

Install `office` for approved OOXML lazy backends and `office-advanced` for optional pypdf inspection/extraction/deep reopen:

```bash
python -m pip install ".[office]"
python -m pip install ".[office-advanced]"
```

Missing optional Python backends return typed capability errors with installation evidence. Package discovery never upgrades capability by itself. ReportLab is approved and locked for PDF authoring with caller-supplied embedded TrueType fonts; pypdfium2 is approved for bounded PDF page images only. Separately installed applications, executables, daemons, runtimes, and subprocess conversion engines are never discovered or launched. Exact package versions, source artifacts, hashes, licenses, probes, and refusal reasons are in the tracked manifest and notice files linked above.

## Security and resource boundaries

Package preflight bounds ZIP entries, expanded bytes, compression ratios, XML bytes/nodes/depth/attributes/text, media, and embedded package depth. It rejects absolute, traversal, noncanonical, duplicate, special, encrypted, malformed, entity-bearing, or over-limit entries. External relationships and active content are inventory findings, never permission to follow or execute them.

Macros, formulas, PDF actions, links, embedded objects, comments, metadata, and document prose are untrusted data. Encryption detection is not decryption. Signature presence is not certificate, revocation, timestamp, or policy verification, and mutation may invalidate signatures.
