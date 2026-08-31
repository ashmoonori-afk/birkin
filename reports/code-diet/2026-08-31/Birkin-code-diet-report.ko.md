# Birkin 코드 다이어트 전수 감사 보고서

**기준일:** 2026-08-31 · **대상:** 최신 working tree의 tracked + untracked 파일

**원칙:** 사용자 소스와 미커밋 변경은 수정·삭제하지 않고 읽기 전용으로 조사 ·
**측정 단위:** 빈 줄과 `#`, `//` 전체 줄 주석을 제외한 pure LOC

---

## 1. 결론

Birkin에는 **지금 정리할 수 있는 고신뢰 production code 168 LOC**가 있다.
문서화되지 않은 sandbox 편의 API까지 정리 대상으로 인정하면 즉시 후보는
**168-186 LOC**다.

호환성 일몰을 계획적으로 수행하면 추가로 **추정 486-506 LOC**를 줄일 수 있다.
따라서 현실적인 단계별 누적 제거량은 다음과 같다.

| 단계 | 추가 제거량 | 누적 제거량 | 판단 |
|---|---:|---:|---|
| 즉시, 고신뢰 | 168 | 168 | 내부 orphan·단절된 scaffold |
| 즉시, 조건부 API | 0-18 | 168-186 | `sandbox.run_repo_job` 외부 소비자 정책 확인 |
| near-term 호환성 일몰(추정) | 486-506 | **654-692** | 8개 migration group |
| profile 장기 일몰 | 214 | **868-906** | persisted profile migration 종료 뒤 |

이와 별도로:

- **18,172 LOC**는 삭제량이 아니라 250-LOC 상한을 적용할 때 다른 모듈로
  **이동해야 하는 최소 production LOC**다.
- exact duplicate **198 LOC**는 검토 pool이며, 자동 삭제량으로 더하면 안 된다.
- old OMO RPC와 Python diagnostics **272 LOC**는 테스트·CI가 의도적으로
  보존하는 API/feature다. 제거하려면 cleanup이 아니라 명시적 product retirement가 필요하다.
- Office legacy boundary **408 LOC**는 구형 입력을 안전하게 거부·검사하는
  active security contract이므로 유지한다.

### 핵심 판단

Birkin의 주된 비만은 “죽은 코드가 많다”보다 **살아 있는 책임이 소수 모듈에
과도하게 집중된 것**이다. 즉시 삭제는 작지만 확실하고, 큰 개선은 호환성
일몰과 facade-preserving module split에서 나온다.

---

## 2. 조사 범위와 검증 방식

### 인벤토리

| 범위 | 파일 | Pure LOC | 250 LOC 초과 |
|---|---:|---:|---:|
| `birkin/` + `birkin_mnemosyne/` Python | 586 | 96,888 | 66 |
| Python tests | 553 | 83,762 | 71 |
| QA/scripts/benchmarks Python | 63 | 9,464 | 8 |
| Windows C# + macOS Swift, tests 포함 | 303 | 28,921 | 19 |
| JavaScript + TypeScript | 22 | 1,374 | 0 |

### 사용한 검증 채널

1. `git ls-files --cached --others --exclude-standard`로 tracked와 untracked를 함께 수집.
2. 단일 Perl stream으로 파일별 pure LOC 측정.
3. Python AST로 587개 파일, 3,713개 top-level definition, 5,072개 함수·메서드 분석
   (인벤토리 표의 586은 빈 파일 `birkin/schemas/__init__.py`를 제외한 LOC 집계 기준).
4. ast-grep으로 실제 import/call shape 확인.
5. `rg --hidden`으로 untracked 파일까지 포함한 symbol/module/dynamic-string counter-search.
6. `git log -S`, `git log -G`, `git show`, `--follow`로 도입·대체·일몰 이력 확인.
7. Ruff `F401,F811,F841` 검사: unused import/local 오류 없음.
8. OMO replacement 관련 focused tests 18개 통과.
9. 독립 감사 lane과 adversarial debate를 반복하고, 새 후보가 나오지 않는
   final convergence pass로 종료.

### 검증 제한

- LSP daemon pipe가 열리지 않아 LSP references/diagnostics는 사용할 수 없었다.
  이를 “참조 없음”으로 간주하지 않고 AST, ast-grep, `rg`, tests, packaging,
  Git history로 대체했다.
- 문서화되지 않은 외부 Python import는 저장소 내부 증거만으로 완전히 부정할 수 없다.
  따라서 public API처럼 보이는 항목은 조건부 또는 유지로 분류했다.

근거: `inventory.md`, `observation-manifest.md`, `claim-graph.md`.

---

## 3. 즉시 삭제 가능

### 3.1 고신뢰 168 LOC

| ID | 위치 | LOC | 삭제 근거 | 대체·이력 |
|---|---|---:|---|---|
| D-002 | `birkin/office/create_schema.py` | 87 | tracked+untracked에서 정의 외 소비자 0; ast-grep call 0 | `7b782ae2`가 `create_document`를 `office_job_request`로 대체 |
| D-003 | `birkin/office/conversion_tool.py` | 22 | import/call/test/docs/registry 0 | 같은 canonical Office approval 전환에서 tool registration 제거 |
| D-004 | `birkin/office/conversion_schema.py:21-34` | 14 | `budget_schema()` 소비자 0 | `LOSS_CATEGORIES`는 유지 |
| D-005 | `birkin/office/export_copy.py` | 21 | module/symbol 소비자 0 | `export_io.copy_exact` + `ExportCommit`, `c59566a5` |
| D-006 | `birkin/office/ir_nodes.py` | 8 | `DocumentNode` 선언 외 소비자 0 | `19e076e1`의 unwired scaffold |
| D-007 | `birkin/office/ir_package.py` | 8 | `PackagePart` 선언 외 소비자 0 | `19e076e1`의 unwired scaffold |
| D-008 | `birkin/office/locators.py` | 5 | module과 두 helper 소비자 0 | adapter별 locator/fingerprint가 active |
| D-011 | `birkin/office/ir_locators.py` | 3 | `SourceLocator` 선언 외 소비자 0 | `19e076e1`의 unwired scaffold |
|  | **합계** | **168** |  |  |

각 항목은 다음 두 종류 이상의 독립 근거를 통과했다.

- AST/ast-grep definition-call closure
- tracked+untracked full-tree reference search
- parser/registry/package/docs/test counter-search
- replacement commit 또는 현재 canonical implementation 확인

### 3.2 조건부 18 LOC

`birkin/sandbox.py:136-153`의 `run_repo_job()`은 repository 내부와 tests에서
소비자가 없다. 현재 구현은 `WorktreeRunner`와 `DockerRunner`를 직접 사용한다.
다만 module-level public function이고 `.birkin/sandbox.json` 계약을 감싸므로
외부 import 정책을 확인한 뒤 삭제해야 한다.

### 3.3 삭제 후보에서 제외한 오탐

| 후보 | 제외 이유 |
|---|---|
| `birkin/curation_cli.py` | parser, handler registry, lazy import, tests, docs, persisted audit manifest가 사용 |
| `OmoRpcClient` transport 189 LOC | production default는 `OmoLiveClient`지만 untracked `tests/test_omo_rpc.py`가 직접 API를 검증 |
| `birkin/native/diagnostics.py` 83 LOC | production constructor는 없지만 CI가 행동 테스트를 명시 실행 |
| slash handlers (`_goal` 등) | `@command` decorator registry를 통한 dynamic dispatch |
| platform backend classes | runtime lazy import와 OS별 acceptance tests가 사용 |

근거: `dead-code-ledger.md`, `debate-log.md` rounds 1, 5, 8, 9.

---

## 4. 선행 마이그레이션 후 삭제 가능

### 4.1 Near-term 8개 group: 추정 486-506 LOC

| Group | 추정 net LOC | 현재 소비자 | 삭제 선행조건 |
|---|---:|---|---|
| Morpheus/nightly compatibility | 31 | CLI/slash alias, config migration, scheduler, status API, schema | persisted config와 외부 CLI/API cutoff |
| Unified workspace compatibility | 360-380 | `dash.snapshot`, `_Keys`, WebUI theme, 308 redirects, `LegacyRunner` | 138 LOC shared closure 이동, old URL/import migration |
| `worker-hook-qa` CLI alias | 9 | README, CLI handler, E2E | module invocation으로 사용자·script migration |
| Workspace `SOUL.md` warning | 12 | prompt assembly, README, warning test | `AGENTS.md`/home `SOUL.md` migration window 종료 |
| Legacy harness session directories | 35 | hashed-key migration과 conflict protection | persisted session directories migration 완료 |
| Legacy parallelization fallback | 6 | callback을 생략하는 direct caller | 모든 caller가 registry posture 제공 |
| Session export legacy flags | 4 | parser fixture, CLI compatibility | external script cutoff |
| Legacy approval execution records | 29 | durable `approving`/`executing` records | old journal이 남지 않는 storage retention 증명 |

Workspace group을 제외한 7개 group의 LOC는 소비자 라인 범위에서 산정한
추정치이며, 실제 일몰 cutoff 시점에 재측정해야 한다.

### 4.2 왜 dash.py 477 LOC를 그대로 더하지 않았나

`workbench.py`가 `dash.snapshot`과 `_Keys`를 아직 사용한다. AST closure 138 LOC와
import·상수 오버헤드를 포함해 138-157 LOC를 새 canonical module로 이전해야 하므로,
gross 477 LOC 중 net obsolete는 약 320-339 LOC다. 여기에 theme re-export 23 LOC,
redirects 약 15 LOC, `LegacyRunner` 약 3 LOC를 더하고 중복을 보수적으로 조정해
workspace migration group을 약 360-380 LOC로 계산했다.

### 4.3 장기 profile migration 214 LOC

`birkin/profile_migration.py`는 legacy `Profile - *` note, archive, conflict,
rollback, idempotency를 보호한다. migration telemetry 또는 명시적 support
cutoff가 생기기 전에는 삭제하면 안 된다.

근거: `legacy-ledger.md`, `debate-log.md` rounds 4, 6.

---

## 5. 스파게티 구조: 삭제가 아니라 이동

저장소 규칙인 모듈당 250 pure LOC 상한을 적용해 이동량을 산정했다.

### 구조적 최소 이동량

| 범위 | 대형 모듈 | 250 LOC 이하로 만들 최소 이동 |
|---|---:|---:|
| Production Python | 66 | 16,818 |
| Native production | 12 | 1,354 |
| **합계** | 78 | **18,172** |

### 우선 분할 대상

| 우선순위 | 모듈 | Pure LOC | 최소 이동 | 분리할 책임 |
|---:|---|---:|---:|---|
| 1 | `birkin/web/server.py` | 1,539 | 1,289 | HTTP server, bootstrap/auth, workspace runtime, API routes, browser, approvals |
| 2 | `birkin/gateway/channels/telegram.py` | 1,385 | 1,135 | transport, callback, progress, formatting, turn lifecycle |
| 3 | `birkin/cli.py` | 1,325 | 1,075 | command family handlers와 thin dispatch |
| 4 | `birkin/skills/manager.py` | 1,205 | 955 | manager, POSIX/Windows publication, proposal apply |
| 5 | `birkin/memory.py` | 1,166 | 916 | search, write, scope/trust, frontmatter, tool boundary |
| 6 | `birkin/harness.py` | 1,133 | 883 | persistence, migration, refine, apply/history |
| 7 | `birkin/gateway/core.py` | 1,099 | 849 | streams, policies, companion, sessions, orchestration |
| 8 | `birkin/llm.py` | 907 | 657 | transports, stream codecs, message conversion, failover |

### 함수 hotspot (발췌)

- `memory.py:903-1161` `VaultMemory.tools`: 248 LOC
- `skills/manager.py:792-1049` `_publish_skill_bytes_windows`: 242 LOC
- `skills/bundle_publish_windows.py:30-259` `publish_windows`: 220 LOC
- `computer_use/service_mutations.py:21-205` `_mutate`: 185 LOC
- `mcp_server.py:41-246` `_build_tools`: 181 LOC
- `office/artifact_publication.py:77-243` `publish_once`: 165 LOC
- `approval_dispatch.py:68-223` `execute_action`: 151 LOC

281개 함수가 50 LOC를 넘고, 47개가 100 LOC, 13개가 150 LOC를 넘는다.
이들은 테스트로 behavior를 고정한 뒤 facade를 유지하며 분할해야 한다.

### Duplicate pool

exact body hash는 naive 449 LOC를 찾았지만:

- Protocol/ellipsis body 244 LOC 제외
- 이미 dead 후보에 들어간 7 LOC 제외
- 나머지 198 LOC는 `birkin`/`birkin_mnemosyne`의 의도적 import boundary,
  platform/channel adapter, security helper가 대부분

따라서 198 LOC는 review pool일 뿐 총 제거량에 넣지 않는다.

근거: `spaghetti-ledger.md`.

---

## 6. 유지 권고

| 범위 | LOC | 유지 이유 |
|---|---:|---|
| Office legacy conversion/preflight/types | 408 | untrusted old Office input을 안전하게 식별·거부하는 active security boundary; 지원 기능 제거이므로 다이어트 수치에서 제외 |
| `repl.run_legacy()` | 166 | 현재 terminal path가 호출 |
| OMO subprocess RPC API | 189 | direct API tests가 존재; 제거는 명시적 API retirement |
| Python `DiagnosticRing` | 83 | CI-pinned behavior contract; 제거는 feature retirement |
| Windows/macOS native trees | 28,921 source+test | CI, golden vectors, bridge lifecycle, clients가 사용 |
| workspace public re-exports | 약 30-40 | Native, terminal, WebUI, scripts가 import |
| `birkin_mnemosyne` engine duplication | 측정 제외 | 설계 문서가 Birkin engine과의 import boundary를 의도적으로 제한 |

---

## 7. 실행 권고 순서

| Track | 시작 | 다음 gate | 최종 상태 |
|---|---|---|---|
| 삭제 | orphan 168 LOC | Sandbox API +18 결정 | migration 후 누적 654-692 |
| 구조 | characterization tests | facade-preserving split | 최소 18,172 LOC 이동 |
| 장기 | persisted profile scan | support cutoff | 누적 868-906 |

### P0 — 가장 안전

1. D-002..D-008, D-011 behavior baseline 확인.
2. orphan file/function 삭제.
3. package build, Office tests, static scan.

예상 production 감소: **168 LOC**.

### P1 — API와 compatibility 결정

1. `run_repo_job` public API 정책 결정.
2. nightly/workspace/worker/SOUL/session/approval migration cutoff 명문화.
3. telemetry 또는 persisted-data scan으로 cutoff 증명.

누적 production 감소: **654-692 LOC**.

### P2 — 구조 분할

`web/server.py`, Telegram, CLI, SkillManager, Memory, Harness, Gateway, LLM
순서로 public facade를 유지하며 책임별 module extraction을 수행한다.
이 작업은 code deletion과 별도 프로젝트로 관리한다.

### P3 — 장기

Profile migration 지원을 종료할 수 있을 때 누적 감소는 **868-906 LOC**다.

---

## 8. 검증 판정

| 성공 기준 | 판정 | 증거 |
|---|---|---|
| 고신뢰 삭제 후보마다 2개 이상 독립 근거와 LOC | PASS | `dead-code-ledger.md`, O-006/O-012/O-013/O-014 |
| 삭제 LOC와 이동 LOC 분리 | PASS | 168-186 deletion vs 18,172 movement |
| caller/registry/test/package counter-search | PASS | AST, ast-grep, full-tree `rg`, tests, packaging |
| legacy를 delete-now/migration/retain으로 분류 | PASS | `legacy-ledger.md`, C-003A/B/C |
| skeptic 반론과 수렴 | PASS | `debate-log.md` 9 rounds, final no-new-lead pass |
| source code 비변경 | PASS | 조사 산출물은 `.omo/ulw-research/20260831-code-diet/`에만 작성 |
| LSP 검증 | UNAVAILABLE | daemon pipe unreachable; 대체 채널 명시 |

---

## 9. 최종 숫자

| 구분 | 최종 값 |
|---|---|
| 권고 삭제량 | 지금 168-186 LOC |
| Near-term 누적(추정) | 654-692 LOC |
| Profile sunset 누적 | 868-906 LOC |
| 구조 다이어트 | 삭제와 별도로 최소 18,172 LOC 이동 |
| 권고하지 않는 추가량 | OMO RPC/diagnostics retirement +272 LOC; Office legacy support removal +408 LOC |

이 숫자는 production LOC만 합산했다. Test/QA cleanup, gross file size,
duplicate review pool, refactor movement는 더하지 않았다.

---

## 부록 A. 증거 파일

- `inventory.md`
- `dead-code-ledger.md`
- `spaghetti-ledger.md`
- `legacy-ledger.md`
- `observation-manifest.md`
- `intent-diff.md`
- `claim-graph.md`
- `debate-log.md`
- `verification-economics.md`
- `journal.md`

## 부록 B. 잔여 위험

1. 문서화되지 않은 외부 Python imports는 저장소만으로 완전히 증명할 수 없다.
2. compatibility 제거 전에는 release cutoff와 persisted-data scan이 필요하다.
3. 미커밋 working tree가 감사 기준이므로 이후 source 변경 시 LOC와 참조를 재계산해야 한다.
4. LSP가 복구되면 D-002..D-008/D-011에 대해 references 결과를 추가하는 것이 바람직하다.
