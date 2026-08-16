# Office Work OS v2

This shipped contract describes registered runtime behavior, not theoretical package features.

- Birkin version: `0.4.227`
- `catalog_revision: 4`
- `inventory_sha256: 66ac4638ee7a8b4f6b68325b036ca7d9b312fdf37eef9b90f3c163a756356d53`
- Machine publication: [`provenance_manifest.json`](../birkin/office/adapters/provenance_manifest.json)
- Generated evidence: [`THIRD_PARTY_NOTICES.md`](../birkin/office/adapters/THIRD_PARTY_NOTICES.md)

The tracked catalog and these generated package-tree files are the publication authority. No ignored `.omo` research file is required to interpret or verify support.

## Runtime support matrix

- `bounded`: a registered implementation covers only the stated subset.
- `conditional`: an approved lazy dependency may be required.
- `template-only`: HWPX creation derives from a trusted template.
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
| `hwpx` | bounded | template-only | bounded | structural | layered | bounded | bounded | structured-preview |
<!-- office-support-matrix:end -->

### Format boundaries

| Format | Current bounded behavior | Explicit boundary |
|---|---|---|
| DOCX | Paragraph creation, package inspection/extraction, layered validation/comparison, TXT projection, and one tagged content-control edit. | No tracked-change synthesis, arbitrary rewrite, or layout proof. |
| XLSX | Scalar-row creation, cell extraction, layered validation/comparison, TXT projection, and one existing sheet-1 cell edit. | Formulas are preserved but never evaluated or recalculated. |
| PPTX | Title/body creation, text extraction, layered validation/comparison, TXT projection, and one slide-1 placeholder edit. | No master, animation, media, overflow, or layout proof. |
| PDF | Built-in ASCII text-first creation; optional pypdf inspection/extraction; structural validation and TXT projection. | Non-Latin creation returns a typed refusal. Existing content is read-only: no OCR, form fill, annotation, signing, redaction, or object rewrite. |
| HWPX | Trusted-template field derivation, extraction, validation/comparison, TXT projection, and one section-0 field edit. | No blank authoring, legacy HWP, Hancom automation, PDF export, or typography proof. |

## Registered tools and arguments

The exact registered set is `list_document_adapters`, `inspect_document`, `extract_document`, `create_document`, `compare_documents`, `fill_template`, `apply_document_patch`, `render_artifact`, `validate_artifact`, and `convert_document`.

| Tool | Required arguments | Important optional arguments/behavior |
|---|---|---|
| `list_document_adapters` | none | Returns the authoritative catalog. |
| `inspect_document` | `source` | Existing artifacts must be inspected first. |
| `extract_document` | `source` | `projection`, `max_spans`, `max_nodes`, `max_text_bytes`. |
| `create_document` | `format`, `content`, `output_name` | `template` is required by HWPX and rejected for other formats. |
| `compare_documents` | `left`, `right` | Returns separate byte, semantic, package, and visual claims. |
| `fill_template` | `template`, `bindings`, `output_name` | Verifies and reads the in-jail template to bind a hash/format-specific plan; it does not write a file. |
| `apply_document_patch` | `base`, `patch`, `expected_source_sha256`, `output_name` | `dry_run` defaults to true; only one narrow operation is accepted. |
| `render_artifact` | `artifact` | `output_format` is `structured_preview`, `pdf`, `png`, or `thumbnail`; `page` is optional. |
| `validate_artifact` | `artifact` | Reports package, schema-root, formula, openability, security, and fidelity layers. |
| `convert_document` | `source`, `target_format`, `output_name`, `loss_budget` | Only UTF-8 `txt` is accepted. |

The seven synchronized skill IDs are `office-work-os`, `office-documents`, `word-documents`, `spreadsheets`, `presentations`, `pdf-documents`, and `korean-hwp-documents`. Their machine metadata requires the same ten-tool set.

## Workspace input jail

`BIRKIN_HOME` is the document workspace jail, not only an output location. Every source and HWPX template URI must be an absolute regular file inside it and its bytes must match `content_hash`. For example, with `BIRKIN_HOME=/workspace/.birkin`, first copy or import inputs under `/workspace/.birkin/artifacts/incoming`. `/workspace/source.docx`, `/tmp/source.docx`, and symlink escapes are rejected.

Outputs are basename-only new files under `/workspace/.birkin/artifacts/drafts`. Creation, conversion, and mutation use no-replace publication; mutation is copy-on-write and rechecks source identity.

Inspect and extract inside the jail:

```text
inspect_document
{"source":{"content_hash":"<sha256>","uri":"/workspace/.birkin/artifacts/incoming/source.docx"}}

extract_document
{"source":{"content_hash":"<sha256>","uri":"/workspace/.birkin/artifacts/incoming/source.docx"},"projection":"text","max_spans":1000,"max_nodes":1000,"max_text_bytes":100000}
```

Create a DOCX draft:

```text
create_document
{"format":"docx","content":{"paragraphs":["Quarterly report"]},"output_name":"quarterly-draft.docx"}
```

HWPX uses the same call with `format: "hwpx"`, field-binding content, and an in-jail `template` artifact. This is template derivation, not blank authoring.

Convert to TXT with the required explicit loss budget:

```text
convert_document
{"source":{"content_hash":"<sha256>","uri":"/workspace/.birkin/artifacts/incoming/source.docx"},"target_format":"txt","output_name":"source.txt","loss_budget":{"structure":100,"style_layout":100,"formula_cache":100,"chart_media":100,"macro_active_content":0,"tracked_changes_comments":100,"form_field":100,"metadata":100,"signature_encryption":0,"accessibility":100}}
```

Omitted loss categories default to zero. Active content and signed/encrypted sources are refused regardless of budget. TXT is a deterministic bounded projection, never native or lossless conversion.

## Comparison, validation, and rendering

`compare_documents` is not byte-only. It always reports hashes and byte equality, attempts normalized semantic comparison under node/text limits, and compares ZIP package entries, relationships, content types, and XML for package formats. PDF package comparison is explicitly unavailable. Visual comparison is always a separate unavailable result; semantic equality never aliases visual equality.

`validate_artifact` reports each attempted, unsupported, and not-run layer. Structural validity does not establish full conformance, accessibility, signature trust, recalculated formulas, openability in a desktop suite, or rendered fidelity.

A semantic preview succeeds as follows:

```text
render_artifact
{"artifact":{"content_hash":"<sha256>","uri":"/workspace/.birkin/artifacts/incoming/source.docx"},"output_format":"structured_preview"}
```

The result has `render_kind: "structured_preview"`, `evidence_class: "semantic_preview"`, and `visual_proof: false`. Requests for `pdf`, `png`, or `thumbnail` return `RENDER_UNAVAILABLE`; this visual refusal must not be reported for a successful structured preview.

## Dependencies and provenance

Install `office` for approved OOXML lazy backends and `office-advanced` for optional pypdf inspection/extraction/deep reopen:

```bash
python -m pip install -e ".[office]"
python -m pip install -e ".[office-advanced]"
```

Missing optional backends return typed capability errors with installation evidence. Package discovery never upgrades capability by itself. ReportLab remains a refused provenance record and has no runtime execution or install-hint path; unpublished HanDoc candidates remain refused, and pypdfium2 remains unwired and does not enable visual rendering. Exact package versions, source artifacts, hashes, licenses, probes, and refusal reasons are in the tracked manifest and notice files linked above.

## Security and resource boundaries

Package preflight bounds ZIP entries, expanded bytes, compression ratios, XML bytes/nodes/depth/attributes/text, media, and embedded package depth. It rejects absolute, traversal, noncanonical, duplicate, special, encrypted, malformed, entity-bearing, or over-limit entries. External relationships and active content are inventory findings, never permission to follow or execute them.

Macros, formulas, PDF actions, links, embedded objects, comments, metadata, and document prose are untrusted data. Encryption detection is not decryption. Signature presence is not certificate, revocation, timestamp, or policy verification, and mutation may invalidate signatures.
