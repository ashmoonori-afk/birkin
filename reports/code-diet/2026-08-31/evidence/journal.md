# Research Journal

## 2026-08-31T09:36:42+09:00 — Scope wave
- 활성 스킬과 Birkin 장기 메모리를 조사했다.
- 저장소는 `main`이 `origin/main`보다 110커밋 뒤이며 대규모 미커밋 변경이 있다. 읽기 전용으로 고정했다.
- 초기 병렬 lane 3개를 완료했다: dead-code, spaghetti, legacy.
- 초기 수치는 claim 후보로만 등록했고 직접 검증 전 최종 보고서 사용을 금지했다.
- format-proposal gate를 열었다.

## 2026-08-31T09:42:00+09:00 — Format decision
- 사용자가 별도 형식 선택 없이 목표 continuation을 지시했다.
- ulw-research 기본안인 한국어 PDF + DOCX를 확정했다.
- 보고서 구조는 경영 요약 2쪽, 정량 후보표, 근거 부록이다.

## 2026-08-31T09:50:00+09:00 — Team fallback and inventory
- 두 번의 team runner 기동이 category 조합과 무관하게 실패했다.
- 두 팀을 강제 삭제했고, 5개 background explore 검증 lane을 추가했다.
- 초기 3개 lane과 합쳐 8개 독립 축을 확보했다.
- 재현 가능한 Perl 스트림 카운터로 working-tree tracked+untracked source inventory를 완료했다.
- 원본 수치와 대형 파일 표는 `inventory.md`에 저장했다.

## 2026-08-31T10:00:00+09:00 — Dead-code direct verification
- Ruff unused import/local scan passed.
- Python AST scanned 587 files and 3,713 top-level definitions without parse errors.
- ast-grep and Git history refuted the initial `curation_cli.py` candidate.
- `b81ea0dd` replaced the old subprocess OMO transport with the exact live bridge; focused tests passed.
- Office canonical-approval and durable-export commits left several unreferenced modules behind.
- High-confidence delete-now total changed from the initial 0 LOC hypothesis to 354 LOC.
- Medium-confidence immediate range is 83-101 LOC.
- Full evidence and arithmetic are in `dead-code-ledger.md`.

## 2026-08-31T10:08:00+09:00 — Structural verification
- Mechanical 250-LOC relocation lower bound: 18,172 production LOC.
- AST function inventory: 5,072 functions, 281 over 50 LOC, 47 over 100, 13 over 150.
- Exact-body duplicate scan found a 198-LOC semantic review pool after protocol stubs and already-dead code were excluded.
- No extra deletion amount was inferred from size or duplication.
- Full evidence is in `spaghetti-ledger.md`.

## 2026-08-31T10:18:00+09:00 — Legacy lifecycle verification
- Named eight near-term compatibility sunset groups: 486-506 production LOC.
- Profile migration adds 214 LOC only after a longer persisted-data cutoff.
- Office legacy input code is an active 408-LOC security/refusal boundary and stays.
- The initial exact-seven-groups claim was refuted.
- Full evidence is in `legacy-ledger.md`.

## 2026-08-31T10:20:00+09:00 — EXPAND wave 1
- Spawned three independent read-only counter-audits: hidden consumers, arithmetic, and long-tail candidates.
- This wave determines whether the current candidate ledger converged or needs another expansion.

## 2026-08-31T10:50:00+09:00 — EXPAND correction
- Hidden-consumer review exposed the tracked-only `git grep` blind spot.
- Full-tree `rg` found untracked OMO RPC contract tests and CI-pinned diagnostics tests.
- Recommended immediate deletion was corrected to 165-183 LOC.
- OMO RPC and diagnostics moved into an optional 272-LOC API/feature-retirement bucket.
- Arithmetic challenges to the 18,172 movement bound and 198 non-additive duplicate pool were rejected with direct ledger evidence.

## 2026-08-31T11:00:00+09:00 — EXPAND wave 2
- Wave 1 long-tail audit found no additional high-confidence candidate.
- Because wave 1 corrected the candidate ledger, a second full-tree and arithmetic convergence pass was launched.

## 2026-08-31T11:12:00+09:00 — Skeptic response
- The skeptic re-read stale headline sections rather than the appended EXPAND correction.
- Its arithmetic blockers were checked against current line items and rejected.
- The external-public-API uncertainty was retained as residual risk.

## 2026-08-31T11:48:00+09:00 — Convergence steer
- The last full-tree lane remained active with continued tool work.
- It was ordered to stop broad exploration and return an immediate terminal candidate/no-candidate/blocked verdict.

## 2026-08-31T11:52:00+09:00 — New convergence lead
- `office/ir_locators.py` was independently found and directly confirmed as a 3-LOC orphan.
- Recommended immediate total increased to 168-186 LOC.
- A final no-new-lead pass is required before convergence.

## 2026-08-31T11:54:00+09:00 — Final convergence pass
- Revived the resident full-tree lane for one bounded no-new-lead pass after D-011.

## 2026-08-31T12:10:00+09:00 — Convergence achieved
- Final tracked+untracked pass found no candidate beyond D-011.
- Research axes converged and final report synthesis may begin.

## 2026-08-31T12:20:00+09:00 — Korean report source
- Created the single-source Korean report with final disjoint totals and evidence references.

## 2026-08-31T12:40:00+09:00 — Render and visual capture
- Generated DOCX/PDF/chart and rendered all PDF pages to fresh PNG evidence.
- Fixed orphan heading, raw Mermaid, final-number border, and sparse-last-page defects.
- Final PDF has seven nonblank pages and the DOCX package validates.
- Two independent visual QA passes are active.

## 2026-08-31T13:00:00+09:00 — Visual QA fix round
- CJK reviewer found three blockers in bold, list continuation, and path wrapping.
- Fixed all blockers plus ordered numbering and chart placement.
- Re-rendered seven fresh pages and launched two fresh reviewers.

## 2026-08-31T13:18:00+09:00 — Visual QA fix round 2
- Functional reviewer found table-header contrast, metadata flow, and DOCX style-mutation blockers.
- Fixed the blockers and chart legend.
- Launched two fresh R3 reviewers on the current seven-page build.

## 2026-08-31T13:36:00+09:00 — Final visual fix
- Reconciled the 586-file evidence count.
- Added DOCX navy/white headers, preserved Normal 9pt, removed empty table runs, and removed the §6 orphan qualifier.
- Launched two fresh R4 reviewers.

## 2026-08-31T13:42:00+09:00 — Functional visual approval
- R4 functional reviewer passed the current artifacts with no blockers.

## 2026-08-31T13:48:00+09:00 — Visual gate complete
- R4 functional and CJK reviewers both passed the current seven-page PDF/DOCX build with no blockers.
- Final writing proofreader started.

## 2026-08-31T13:50:00+09:00 — Proofreader fallback
- Writing-category provider had insufficient credits and returned no review.
- Started an unspecified-high Korean proofreader with the same gate.

## 2026-08-31T14:18:00+09:00 — Proofreader steer
- The long-running fallback reviewer was ordered to stop searching and return its terminal verdict.

## 2026-08-31T14:32:00+09:00 — Proofread correction round
- Proofreader reproduced the arithmetic and identified five publication blockers.
- Corrected citations, AST/LOC scope, API wording, workspace derivation, and migration estimate labels.
- Re-rendered and launched final visual R5 + proofread R2 approvals.

## 2026-08-31T14:36:00+09:00 — Functional R5 approval
- Current proofread-corrected build passed functional visual QA with no blockers.

## 2026-08-31T14:40:00+09:00 — CJK R5 approval
- Current proofread-corrected build passed CJK visual QA with no blockers.

## 2026-08-31T14:52:00+09:00 — Proofread R2 steer
- Ordered the final proofreader to stop further checks and return its terminal verdict.

## 2026-08-31T15:05:00+09:00 — Publication approval and cleanup
- Proofread R2 passed with no blockers.
- Final visual R5 and proofread R2 all approve the current build.
- Deleted teams, terminal sessions, pycache, and temporary report artifacts; standalone cleanup check returned CLEAN.

## 2026-08-31T15:12:00+09:00 — Completion audit
- Every explicit success criterion mapped to current evidence and passed.
- Final PDF/DOCX/Markdown artifacts, reviews, cleanup, and todo state are ready for goal completion.

## 2026-08-31T13:26:00+09:00 — Visual CJK approval
- R3 CJK reviewer passed all seven fresh pages with no blockers.

## 2026-08-31T11:52:00+09:00 — New convergence lead
- `office/ir_locators.py` was independently found and directly confirmed as a 3-LOC orphan.
- Recommended immediate total increased to 168-186 LOC.
- A final no-new-lead pass is required before convergence.
