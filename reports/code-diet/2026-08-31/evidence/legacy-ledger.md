# Legacy and compatibility retirement ledger

Status: current consumers, tests/docs, and local Git lifecycle verified.

## Migration-gated production deletion

| Group | Net removable production LOC | Current consumers | Sunset prerequisite | History / replacement |
|---|---:|---|---|---|
| Morpheus/nightly compatibility | 31 | CLI rewrite, slash alias, persisted config migration, scheduler fallback/alias, status API fields, dashboard/statusline, deprecated schema keys | Release cutoff plus migration of persisted `nightly_*` keys and external CLI/API consumers | `45efb77d refactor: rename the nightly routine to "Morpheus"`; `docs/DECISIONS.md:1449-1488` intentionally retains aliases |
| Unified workspace compatibility | 360-380 | `workbench.py` imports `dash.snapshot` and `_Keys`; WebUI exports legacy theme contract; three old URLs return 308; terminal accepts `LegacyRunner` | Move the 138 LOC still reused from `dash.py`, migrate web imports and external bookmarks, then remove old render/redirect seams | `b84cd39c feat(workspace): unify terminal and web chat`; tests in `bf5d4fea`; docs in `c6db2e81` |
| `worker-hook-qa` CLI alias | 9 | README tables, CLI handler registry, E2E compatibility test | Remove advertised alias after callers use `python -m birkin.worker_hook_qa` | Deprecated wrapper in `cli.py:82-90`; canonical module remains |
| Workspace `SOUL.md` warning | 12 | `prompts.workspace_prompt_block`, README, one warning test | Release cutoff after workspace instructions have migrated to `AGENTS.md` and persona to home `SOUL.md` | Canonical precedence is documented in README; warning is intentionally transitional |
| Legacy harness session directories | 35 | `harness_dir()` migrates raw directory names into hashed keys with conflict protection | Migrate all persisted session directories and define retention cutoff | `_legacy_session_key` plus migration block in `harness.py:75-115` |
| Legacy parallelization fallback | 6 | Direct callers that omit `can_parallelize`; registry callers already pass posture classification | Require every public caller to pass registry classification and remove fallback API behavior | `_legacy_can_parallelize` and optional callback branch in `parallel.py:33-56` |
| Session export legacy flags | 4 | parser fixture and `cli.py:1024-1027` | CLI release cutoff and external script migration | Canonical session export remains |
| Legacy approval execution records | 29 | durable records in `approving`/`executing` formats | Storage-retention boundary proving no old record can remain | `_migrate_legacy` in `approval_execution_recovery.py:211-244`; security-sensitive data migration |

Near-term migration-gated total: **486-506 pure production LOC**.

### Workspace arithmetic

- `dash.py`: 477 pure LOC.
- `workbench.py` directly reuses `snapshot` and `_Keys`; AST closure adds `_agent_age` and `_mtime_age`.
- Required relocation from `dash.py`: 138 pure LOC plus small import/constants overhead.
- Net obsolete dash implementation: approximately 320-339 LOC.
- `workspace_theme.py`: 23 LOC, fully replaceable by `workspace.theme`.
- Legacy route enum/set/matcher/308 branch: approximately 15 LOC.
- `LegacyRunner` type/argument/callback seam: approximately 3 LOC.
- Rounded group range: 360-380 LOC net deletion after migration.

## Long-term migration code

| Group | Pure LOC | Why retained now | Removal condition |
|---|---:|---|---|
| `profile_migration.py` | 214 | `/profile migrate` and rollback protect existing `Profile - *` notes, archive state, conflicts, and repeated-run idempotency | Verified migration telemetry or explicit support cutoff for all legacy profile notes |

Near-term plus profile sunset: **700-720 production LOC**.

## Retain unless product support is explicitly removed

| Group | Pure LOC | Reason |
|---|---:|---|
| Office legacy input boundary: `legacy_conversion.py`, `legacy_preflight.py`, `legacy_types.py` | 408 | Active identity/preflight/refusal contract with direct tests. “Legacy” describes untrusted input, not obsolete implementation. |
| `repl.run_legacy()` | 166 | Active terminal path called by `repl.run`; removing it requires a terminal architecture migration. |
| Native Windows/macOS protocol trees | 28,921 combined source+test inventory | CI, shared golden vectors, bridge lifecycle, and native clients actively consume them. |
| Workspace protocol re-exports | about 30-40 | Native, terminal, WebUI, scripts, and vector generation import them as public contracts. |

If the product explicitly drops legacy Office input handling, the theoretical additional removal is **408 LOC**, but this is a feature removal, not cleanup. It is excluded from recommended savings.

## Test and QA cleanup, reported separately

| Artifact | Pure LOC | Gate |
|---|---:|---|
| `script/qa/workspace_legacy_e2e.py` | 204 | Delete after URL/API deprecation window |
| `tests/test_workspace_legacy_migration.py` | 91 | Delete or rewrite when redirects and compatibility API assertions retire |
| `tests/test_native_diagnostics.py` | 68 | Delete with medium-confidence `DiagnosticRing` candidate |
| OMO legacy helper/platform assertions | small targeted subset | Update when the subprocess transport is removed |

Test/QA LOC does not increase production deletion totals.

## Group-count verdict

- Exactly seven groups was not authoritative.
- Direct manifest: **8 near-term migration groups**, **1 long-term profile migration group**, and **3 retain/product-boundary clusters**.
- The initial seven-group claim is refuted; the corrected compatibility inventory is explicit and disjoint.
