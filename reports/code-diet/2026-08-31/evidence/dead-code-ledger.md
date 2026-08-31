# Dead-code candidate ledger

Status: direct lead verification complete for the entries below.
Scope: current dirty working tree plus local Git history.

> Current publication verdict is the EXPAND-corrected `168` high-confidence LOC
> below. The initial `354` table is retained only as an audit trail and is superseded.

## High-confidence delete-now production code

| ID | Candidate | Pure LOC | Independent evidence | Replacement/history | Risk |
|---|---|---:|---|---|---|
| D-001 | Legacy subprocess transport in `birkin/omo_rpc.py`: `default_omo_command` lines 39-51, `command_for_session` lines 54-69, `OmoRpcClient` lines 72-230, transport-only imports | 189 | AST found no `OmoRpcClient` consumer; `git grep` found only the declaration. `command_for_session` is used only by one legacy helper test. `OmoController` imports only shared `OmoState`/`RpcError`. | `b81ea0dd feat(omo): add exact live-session bridge` removed `OmoRpcClient` from the controller and made `OmoLiveClient` the default. `18` focused OMO/platform tests passed. | Low: keep shared JSON types, `OmoState`, and `RpcError`; remove/update two legacy-only tests. |
| D-002 | Entire `birkin/office/create_schema.py` | 87 | ast-grep found zero calls; `git grep` found only its own definition; no tests/docs/package registry refer to the module. | `7b782ae2` removed `create_document` and its `create_content_schema` import when Office mutations moved to canonical `office_job_request`. | Low. |
| D-003 | Entire `birkin/office/conversion_tool.py` | 22 | AST and repository text search found no imports/calls outside the file. | `7b782ae2` removed `convert_document` tool registration and `execute_tool_conversion` import. | Low. |
| D-004 | `budget_schema()` in `birkin/office/conversion_schema.py:21-34` | 14 | AST and exact-text counter-search found only the definition. `LOSS_CATEGORIES` remains consumed by `conversion_audit.py` and QA. | The registered conversion tool was removed in `7b782ae2`. | Low; retain `LOSS_CATEGORIES`. |
| D-005 | Entire `birkin/office/export_copy.py` | 21 | No current import/call/test/doc consumer. Exact-symbol and module counter-searches return only the file itself. | Durable export work replaced it with `export_io.copy_exact` and `ExportCommit`; `c59566a5` is the current recovery boundary. | Low. |
| D-006 | Entire `birkin/office/ir_nodes.py` | 8 | `DocumentNode` appears only in its declaration; module has no importer, test, registry, or documentation consumer. | Introduced by `19e076e1` as a DocumentIR scaffold but never connected to the shipped path. | Low. |
| D-007 | Entire `birkin/office/ir_package.py` | 8 | `PackagePart` appears only in its declaration; module has no importer, test, registry, or documentation consumer. | Introduced by `19e076e1` as a DocumentIR scaffold but never connected to the shipped path. | Low. |
| D-008 | Entire `birkin/office/locators.py` | 5 | Both one-line helpers have no consumers; the module is never imported. | Adapter-specific typed locators and inventories are the active replacement. | Low. |

High-confidence delete-now total: **354 pure production LOC**.

## Medium-confidence delete-now

| ID | Candidate | Pure LOC | Evidence | Why not high confidence |
|---|---|---:|---|---|
| D-009 | Entire `birkin/native/diagnostics.py` | 83 | `DiagnosticRing` has no production import/constructor/registry; only `tests/test_native_diagnostics.py` uses it. macOS owns a separate active `BridgeSupervisorDiagnostic` ring and UI route. | The feature was intentionally introduced by `a7d70e28` and hardened later. It may be unfinished rather than obsolete, so product intent should be confirmed before deletion. |
| D-010 | `run_repo_job()` in `birkin/sandbox.py:136-153` | 18 | Exact search found no caller; active code directly uses `WorktreeRunner`/`DockerRunner`. | It is an undocumented but plausible convenience API for external callers. |

Medium-confidence immediate range: **83-101 pure production LOC**.

## Retain / false positives

| Candidate | Verdict | Evidence |
|---|---|---|
| `birkin/curation_cli.py` | Retain | Parser registration, handler registry, lazy import, tests, docs, and audit-manifest behavior all consume it. ast-grep found the import and call in `cli.py:731-733`. |
| Slash-command handlers such as `_goal` | Retain | `@command(...)` decorator registration is dynamic; absence of direct calls is expected. |
| `MemoryEngine`, `MemoryRetrieval` | Retain | Imported under aliases by `birkin_mnemosyne.mnemosyne` and `memory`. |
| Platform backend classes | Retain | Lazy imports by runtime plus platform acceptance tests. |
| Browser adapter seam | Product decision | No production route, but tests and README explicitly describe an optional contract seam; exclude from delete-now until the product contract is retired. |

## Static and structural evidence

- Ruff `F401,F811,F841`: **All checks passed**. Invalid `# noqa` syntax warnings exist in current untracked gateway split files; no unused-import/local violations were emitted.
- Python AST: 587 production files parsed without syntax errors; 3,713 top-level definitions scanned.
- LSP: unavailable for this workspace because the daemon pipe never became reachable. This channel is recorded as unavailable rather than treated as absence.
- ast-grep: verified `curation_cli` import/call and zero calls for the confirmed orphan Office schema.
- OMO focused tests: `tests/test_omo_live_bridge.py`, `tests/test_omo_gateway.py`, and `tests/test_platform_compatibility.py` passed (`18` tests).

## Arithmetic

- High confidence: `189 + 87 + 22 + 14 + 21 + 8 + 8 + 5 = 354`.
- High + medium lower bound: `354 + 83 = 437`.
- High + full medium upper bound: `354 + 83 + 18 = 455`.
- Test cleanup is reported separately and not included in production LOC.

## EXPAND correction — tracked + untracked search

The first lead pass used `git grep`, which excludes untracked files. A follow-up
`rg --hidden --glob '!.git/**' --glob '!.omo/**'` pass found the active untracked
`tests/test_omo_rpc.py`. The ledger is corrected as follows:

| ID | Corrected verdict | Reason |
|---|---|---|
| D-001 OMO subprocess transport | Retain / explicit API-retirement decision | Current `OmoController` uses `OmoLiveClient`, but untracked `tests/test_omo_rpc.py` directly exercises `OmoRpcClient` twice and the existing gateway test exercises `command_for_session`. This is no longer high-confidence dead code. |
| D-009 Python `DiagnosticRing` | Retain / explicit feature-retirement decision | It has no production constructor, but tracked tests explicitly verify behavior and `.github/workflows/tests.yml:67` runs that test. Tests alone do not make it runtime-reachable, but they prove intentional shipped-contract work. |
| D-002..D-008 | Unchanged PASS | Full tracked+untracked `rg` found only each candidate's own definitions. |
| D-010 `run_repo_job` | Medium-confidence conditional | Full tracked+untracked search still finds only its definition; public module-level API risk remains. |

### Corrected arithmetic

- High-confidence delete-now: `87 + 22 + 14 + 21 + 8 + 8 + 5 = 165`.
- Medium-confidence immediate: `18`.
- Recommended immediate range: **165-183 pure production LOC**.
- Optional explicit API/feature retirement: old OMO RPC `189` + Python diagnostics `83` = **272 LOC**.
- The previous `354` / `437-455` immediate figures are superseded and must not be used.

## Convergence addition — `ir_locators.py`

| ID | Candidate | Pure LOC | Evidence | History |
|---|---|---:|---|---|
| D-011 | Entire `birkin/office/ir_locators.py` | 3 | Full tracked+untracked `rg` finds `SourceLocator` only in its declaration; no import, test, QA, registry, docs, or dynamic consumer. Active adapters own their locator types. | Introduced as an unwired DocumentIR scaffold by `19e076e1`. |

Corrected recommended arithmetic:

- High-confidence delete-now: `165 + 3 = 168`.
- Medium-confidence conditional immediate: `18`.
- Recommended immediate range: **168-186 LOC**.
- Immediate + near-term migration: **654-692 LOC**.
- Immediate + near-term + profile sunset: **868-906 LOC**.
- Optional explicit OMO RPC/diagnostics retirement remains `272 LOC` and is not recommended cleanup.
