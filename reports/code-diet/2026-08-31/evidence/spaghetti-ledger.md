# Structural and spaghetti-code ledger

Status: direct AST and LOC verification complete.

> Dead-code figures in the historical estimate discussion are superseded by the
> final `168` LOC EXPAND correction in `dead-code-ledger.md`.

## Structural baseline

| Metric | Result |
|---|---:|
| Production Python files | 586 |
| Production Python pure LOC | 96,888 |
| Production Python modules over 250 pure LOC | 66 |
| Pure LOC inside those 66 modules | 33,318 |
| Minimum LOC that must move so every original Python module is at most 250 | **16,818** |
| Native production modules over 250 pure LOC | 12 |
| Minimum native LOC that must move to reach 250 | **1,354** |
| Minimum production LOC relocation, Python + native | **18,172** |
| Python functions/methods scanned | 5,072 |
| Functions over 50 pure LOC | 281 |
| Functions over 100 pure LOC | 47 |
| Functions over 150 pure LOC | 13 |
| Functions with branch/loop/match proxy at least 30 | 25 |

`18,172` is a mechanical lower bound for relocation under the 250-pure-LOC rule. It is **not deletion savings**.

## Highest-concentration module clusters

| Module | Pure LOC | Concentrated responsibilities | Diet verdict |
|---|---:|---|---|
| `birkin/web/server.py` | 1,539 | bounded HTTP server, bootstrap/capability authority, workspace runtime lifecycle, status/API routes, browser aside, approvals/checkpoints | Split behind existing WebUI API; 1,289 LOC must leave the file to reach 250. No deletion inferred. |
| `birkin/gateway/channels/telegram.py` | 1,385 | Telegram transport, JSON decoding, trust checks, formatting, callbacks, progress, turn lifecycle | Split transport/callback/progress/turn handling; 1,135 LOC minimum movement. |
| `birkin/cli.py` | 1,325 | 30+ command handlers and final dispatch/compat aliases | Continue the existing `cli_parsers/` decomposition; 1,075 LOC minimum movement. |
| `birkin/skills/manager.py` | 1,205 | skill manager, POSIX publication, Windows publication, proposal application, cleanup | Separate platform publishers and proposal application; 955 LOC minimum movement. |
| `birkin/memory.py` | 1,166 | scoped vault facade, search/write, trust, frontmatter, tool schema, formatting | Split search/write/tool boundary while preserving `VaultMemory`; 916 LOC minimum movement. |
| `birkin/harness.py` | 1,133 | storage paths, legacy session migration, refine requests, state transitions, apply/history/export | Split persistence/migration/refinement/application; 883 LOC minimum movement. |
| `birkin/gateway/core.py` | 1,099 | streams, config parsing, risk/companion contracts, command menu, gateway orchestration | Continue current working-tree gateway split; 849 LOC minimum movement. |
| `birkin/llm.py` | 907 | message conversion, HTTP/CLI transports, stream codecs, client construction, failover | Extract transport and stream codecs behind `LLMClient`; 657 LOC minimum movement. |
| `birkin/slashcommands.py` | 839 | decorator registry plus all slash command handlers | Retain registry/dispatch and move command families; 589 LOC minimum movement. |
| `birkin/runtime.py` | 820 | session orchestration, profiles, harness context, packet/build functions | Extract profile/harness assembly and session construction; 570 LOC minimum movement. |

## Function-level hotspots

| Path:line | Function | Pure LOC | Decision proxy | Why it is spaghetti-prone |
|---|---|---:|---:|---|
| `birkin/memory.py:903-1161` | `VaultMemory.tools` | 248 | 35 | tool schemas, closures, and mutation/search orchestration in one method |
| `birkin/skills/manager.py:792-1049` | `_publish_skill_bytes_windows` | 242 | 43 | platform handles, security, publication, rollback, cleanup |
| `birkin/skills/bundle_publish_windows.py:30-259` | `publish_windows` | 220 | 49 | separate Windows publisher duplicates part of manager responsibility |
| `birkin/computer_use/service_mutations.py:21-205` | `MutationMixin._mutate` | 185 | 29 | tagged action routing and authority checks |
| `birkin/mcp_server.py:41-246` | `_build_tools` | 181 | 27 | schema and handlers for every MCP tool |
| `birkin/repl.py:65-272` | `run_legacy` | 166 | 36 | active terminal compatibility path, not dead code |
| `birkin/office/artifact_publication.py:77-243` | `publish_once` | 165 | 51 | security-sensitive publication transaction |
| `birkin/harness.py:512-682` | `apply` | 159 | 24 | ledger mutation, rollback, and publication |
| `birkin/inline_complete.py:291-465` | `apply_event` | 153 | 41 | terminal editor reducer |
| `birkin/approval_dispatch.py:68-223` | `execute_action` | 151 | 45 | approval category dispatch and result handling |

These are refactor targets, not deletion candidates. Security, transaction, session, and terminal behavior require characterization tests before extraction.

## Exact-duplicate AST scan

- Exact cross-file body groups: `23`.
- Naive duplicate potential: `449` LOC.
- Protocol/ellipsis method bodies: `244` LOC; not implementation duplication.
- Already-counted dead `create_schema` helper: `7` LOC.
- Remaining review pool: **198 LOC**, not proven removable.

The remaining groups are mostly:

- intentionally separated `birkin` and `birkin_mnemosyne` implementations; `docs/soul-preference-design.md` explicitly forbids importing the latter engine into Birkin except the profile boundary,
- repeated six-line hash/resource/security helpers whose forced abstraction would increase coupling,
- platform/channel adapters whose similar bodies have different contracts,
- context-manager exits and protocol-shaped methods.

No additional high-confidence deletion amount is assigned from duplication.

## Refuted initial estimate

The initial agent estimate of `250-690 removable` and `4,000-4,950 movable` LOC is not used:

- It lacked a disjoint candidate manifest.
- Direct verification initially established `354`, later superseded by the
  tracked+untracked EXPAND correction of `168` high-confidence dead LOC.
- Mechanical relocation under the repository's 250-LOC rule is `18,172`, not `4,000-4,950`.
- Relocation is not deletion and must remain a separate number.

## Structural conclusion

- Additional deletion attributable solely to spaghetti structure: **0 LOC proven**.
- High-confidence dead-code deletion is the EXPAND-corrected `168 LOC` in
  `dead-code-ledger.md`; the earlier `354` was refuted.
- Refactor-only minimum movement: **18,172 production LOC**.
- Exact-duplicate review pool: **198 LOC**, currently retained pending semantic consolidation proof.
