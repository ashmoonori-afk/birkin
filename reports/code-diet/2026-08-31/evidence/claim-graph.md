# Claim Graph

## Verified claims digest
아직 없음.

| claim_id | statement | type | risk | scope | intent_ids | support | contradiction | groups | convergence | counter-search | primary source | dependencies | status | synthesis |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C-001 | 현재 delete-now 고신뢰 생산 코드는 0 LOC일 수 있다 | quantitative | high | production | ET-1 | O-001 | pending | dead-code lane | open | pending | repository | direct verification | unresolved | pending |
| C-002 | 구조 다이어트는 250–690 LOC 삭제와 4,000–4,950 LOC 이동일 수 있다 | quantitative | high | architecture | ET-2 | O-002 | pending | spaghetti lane | open | pending | repository | direct verification | unresolved | pending |
| C-003 | 구버전 유물은 delete-now가 아니라 migration-gated다 | compatibility | high | CLI/config/web | ET-3 | O-003 | pending | legacy lane | open | pending | repository/history | direct verification | unresolved | pending |
| C-004 | 최종 합계는 delete-now/deferred/refactor-only를 분리해야 한다 | methodology | medium | report | ET-4 | O-001,O-002,O-003 | none | lead | open | pending | brief | C-001,C-002,C-003 | partial | pending |

## Direct verification update — 2026-08-31T10:00:00+09:00

| claim_id | statement | type | risk | scope | intent_ids | support | contradiction | groups | convergence | counter-search | primary source | dependencies | status | synthesis |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C-001A | High-confidence delete-now code totals 354 pure production LOC | quantitative | high | production | ET-1 | O-005,O-006 | O-001 | lead + initial dead-code | two-group contradiction resolved by direct execution | AST, ast-grep, git grep, history, focused tests | `dead-code-ledger.md` | D-001..D-008 | supported | pending |
| C-001B | Additional medium-confidence delete-now code is 83-101 LOC | quantitative | medium | production | ET-1 | O-007 | product-intent uncertainty | lead | partial | production imports, tests, docs, native implementation | `dead-code-ledger.md` | D-009,D-010 | partial | pending |
| C-001 | Current delete-now total is 0 LOC | quantitative | high | production | ET-1 | O-001 | O-005,O-006,O-007 | dead-code lane vs lead | refuted | direct counter-search complete for confirmed entries | repository | C-001A,C-001B | refuted | unresolved annex |
| C-002A | At least 18,172 production LOC must move to enforce 250 pure LOC per original module | quantitative | medium | architecture | ET-2 | O-008 | O-002 | lead structural scan + initial spaghetti | supported | threshold arithmetic recomputed by file | `spaghetti-ledger.md` | inventory | supported | pending |
| C-002B | Exact duplicate implementation currently proves additional deletion savings | quantitative | medium | architecture | ET-2 | O-009 | contract and package boundaries | lead | refuted | protocol and cross-package groups reviewed | `spaghetti-ledger.md` | exact AST groups | refuted | unresolved annex |
| C-002 | Structural diet is 250-690 removable and 4,000-4,950 movable LOC | quantitative | high | architecture | ET-2 | O-002 | O-005,O-006,O-008,O-009 | initial spaghetti vs lead | refuted | disjoint arithmetic complete | repository | C-002A,C-002B | refuted | unresolved annex |
| C-003A | Near-term migration-gated compatibility deletion is 486-506 LOC | quantitative | high | compatibility | ET-3 | O-010 | external usage unknown | lead + legacy lanes | partial | current callers/tests/history checked | `legacy-ledger.md` | eight sunset groups | supported | pending |
| C-003B | Profile migration adds 214 LOC after a longer retention cutoff | quantitative | high | persisted data | ET-3 | O-010 | no migration telemetry | lead | partial | command/tests/history checked | `profile_migration.py` | profile support cutoff | partial | pending |
| C-003C | Office legacy boundary is ordinary dead legacy code | compatibility | high | security/office | ET-3 | none | O-011 | lead + skeptic | converged refutation | direct tests and active routing | `legacy-ledger.md` | Office support decision | refuted | unresolved annex |
| C-003 | Exactly seven migration groups exist | quantitative | medium | compatibility | ET-3 | O-003 | O-010,O-011 | initial legacy vs lead | refuted | named manifest complete | `legacy-ledger.md` | C-003A,C-003B,C-003C | refuted | unresolved annex |
| C-001D | Corrected high-confidence delete-now total is 165 LOC | quantitative | high | production | ET-1 | O-006,O-012 | O-005,O-007 | lead + hidden-consumer lane | supported | tracked+untracked counter-search complete | `dead-code-ledger.md` correction | D-002..D-008 | supported | pending |
| C-001E | Additional immediate conditional deletion is 18 LOC; OMO RPC and diagnostics require explicit API/feature retirement | policy | medium | production/API | ET-1 | O-012 | active tests/CI | lead + hidden-consumer lane | supported | tests, CI, runtime default, docs searched | `dead-code-ledger.md` correction | D-001,D-009,D-010 | supported | pending |
| C-001A | High-confidence delete-now code totals 354 pure production LOC | quantitative | high | production | ET-1 | O-005,O-006 | O-012 | lead + hidden-consumer lane | refuted after untracked search | tracked-only search limitation resolved | `dead-code-ledger.md` | C-001D,C-001E | refuted | unresolved annex |
| C-001F | Final high-confidence delete-now total is 168 LOC after D-011 convergence addition | quantitative | high | production | ET-1 | O-006,O-012,O-013 | none current | lead + full-tree convergence | open pending no-new-lead pass | tracked+untracked `rg`, history, LOC | `dead-code-ledger.md` | D-002..D-008,D-011 | supported | pending |

## Final verified claims digest — 2026-08-31T12:10:00+09:00

| claim_id | final statement | evidence | convergence |
|---|---|---|---|
| C-001F | High-confidence immediate deletion is 168 pure production LOC | O-006,O-012,O-013,O-014 | supported; final pass found no new candidate |
| C-001E | Additional immediate conditional deletion is 18 LOC; OMO RPC/diagnostics require explicit retirement | O-012 | supported with public-API residual risk |
| C-002A | Refactor-only minimum movement is 18,172 production LOC | O-008 | supported; never deletion |
| C-002B | Exact duplicate review pool is 198 LOC and non-additive | O-009 | supported as review pool only |
| C-003A | Near-term migration-gated additional deletion is 486-506 LOC | O-010 | supported with external-consumer cutoff |
| C-003B | Profile migration adds 214 LOC after long retention | O-010 | partial until migration telemetry/cutoff |
| C-003C | Office legacy 408 LOC remains active | O-011 | supported retain verdict |
