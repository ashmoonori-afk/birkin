# Definition format conversion ROI

분석 기준 브랜치: `analysis/definition-format-roi`
분석 기준 커밋: `32f8555`

## 구현 상태

ROI 4/5 이상 권고는 이 브랜치에서 구현됐다.

- CurationPlan/2 canonical schema와 provider/prompt/parser 통합:
  `cbd25de`
- versioned config schema, typed normalization, 양언어 생성 문서:
  `4c00973`
- versioned cron record와 legacy migration:
  `c8717ac`

## 결론

현재 Birkin에서 workflow 정의와 worker 정의를 TypeScript로 전환하는 ROI는
각각 **2/5 (낮음)** 이다. 둘 다 Python 실행 경로와 사용자 확장 포맷에 직접
결합되어 있어, TypeScript의 정적 타입 이득보다 Node/빌드 체인, Python-Node
브리지, 기존 `.py` 호환성 비용이 더 크다
(`birkin/moirai/engine.py:84-112`, `birkin/moirai/cli.py:25-41`,
`birkin/worker_hooks.py:9-61`, `.github/workflows/tests.yml:14-33`,
`pyproject.toml:1-39`).

현재 가장 높은 ROI는 **CurationPlan의 중복 정의를 단일 versioned JSON
Schema로 통합하는 것**이다. provider가 강제하는 스키마는 v1인데 계약과
프롬프트는 v2이며, v2의 `annotate` 연산을 provider 스키마가 표현하지 못하는
실제 충돌이 있다 (`birkin/providers.py:55-81`,
`birkin/curation_contract.py:8-23`, `birkin/curation_prompt.py:98-122`,
`birkin/curation_cli.py:39-43`).

## 평가 방법

각 후보를 다음 항목의 상대 점수로 평가했다.

- guardrail gain: 잘못된 상태를 작성 또는 로드 시점에 차단하는 정도
- defect evidence: 현재 코드에서 실제 불일치 또는 늦은 실패가 확인되는 정도
- reuse: 하나의 정의가 여러 consumer를 통제하는 정도
- migration cost: 수정 파일, 호환성, 테스트 전환 범위
- operational cost: 새 런타임, 빌드, 패키징, 배포 부담

ROI 점수는 금액 추정치가 아니라 위 항목을 종합한 1-5 우선순위다.

## Workflow 정의의 TypeScript 전환

### 판정: 2/5, 지금은 전환하지 않음

Birkin에는 서로 다른 두 workflow 경계가 있다.

1. Telegram 승인 workflow는 JSON envelope를 Python dataclass로 파싱하고
   저장된 제안을 승인 상태 머신으로 전환한다
   (`birkin/gateway/workflow.py:62-101`,
   `birkin/gateway/workflow.py:117-177`,
   `birkin/gateway/workflow.py:180-281`).
2. Moirai workflow는 `meta`와 `main(m)`을 가진 신뢰된 Python 파일이며,
   loader가 직접 compile/exec하고 runtime이 agent, parallel, pipeline,
   resume을 처리한다 (`birkin/moirai/engine.py:42-112`,
   `birkin/moirai/engine.py:135-184`,
   `birkin/moirai/engine.py:389-429`,
   `birkin/moirai/engine.py:510-548`).

Moirai는 `~/.birkin/moirai/scripts/*.py` 사용자 정의와 bundled `.py`를 함께
탐색하고, CLI·자동 제안·승인 실행·resume이 같은 loader를 사용한다
(`birkin/moirai/cli.py:19-41`, `birkin/moirai/cli.py:117-160`,
`birkin/moirai/trigger.py:89-104`, `birkin/moirai/trigger.py:185-207`).
따라서 TS 전환은 단순 파일 확장자 변경이 아니라 기존 사용자 workflow의
영구 dual-format 지원 또는 migration을 요구한다.

TypeScript가 줄 수 있는 주요 이득은 `m.agent` 옵션, role literal, schema
결과 타입의 작성 시점 검사다. 그러나 현재 runtime의 abort, agent 수 제한,
token budget, binding 검증, persisted resume identity는 실행 시점 검증이라
TS로 대체되지 않는다 (`birkin/moirai/bindings.py:164-219`,
`birkin/moirai/engine.py:208-255`,
`birkin/moirai/journal.py:29-40`, `birkin/moirai/journal.py:106-115`).

현재 저장소는 Python/Hatch 패키지이며 Node manifest, tsconfig, TS source가
없고 CI도 Python 설치·compileall·pytest만 수행한다
(`pyproject.toml:1-49`, `.github/workflows/tests.yml:14-33`).
TS 실행을 추가하면 Node 가용성, compiler/lockfile, wheel artifact,
source map, cross-platform CI, Python callback bridge가 새 운영 비용이 된다.

### 더 작은 대안

Python workflow를 유지하면서 다음을 적용하는 편이 ROI가 높다.

- `MoiraiAPI`와 workflow metadata의 정적 타입을 강화한다
  (`birkin/moirai/engine.py:42-81`, `birkin/moirai/engine.py:135-184`).
- role 사용을 regex 대신 AST로 검사한다
  (`birkin/moirai/engine.py:34-35`, `birkin/moirai/engine.py:69-81`).
- JSON Schema에서 provider runtime schema와 Python 타입 stub을 생성한다
  (`birkin/moirai/schema.py:1-18`, `birkin/moirai/schema.py:24-80`).

## Worker 정의의 TypeScript 전환

### 판정: 2/5, 지금은 전환하지 않음

machine-readable worker taxonomy는 8개 이름, no-model 목록, persistence owner
mapping으로 작다 (`birkin/worker_hooks.py:9-20`). continuation boundary는
exact keys, schema version, handler, worker allowlist, JSON serializability,
16 KiB 제한을 runtime에서 검증한다 (`birkin/worker_hooks.py:38-61`).
proposal 저장 전과 승인 후 dispatch 전에 같은 validator가 다시 적용된다
(`birkin/approvals.py:54-75`, `birkin/approvals.py:210-291`).

실제 worker behavior는 Moirai, Mnemosyne, Neurosis, Morpheus, Boulder,
Harness, Odyssey와 Odyssey protocol 안의 Osiris에 분산되어 있다
(`birkin/worker_hooks.py:9-20`, `birkin/mnemosyne.py:1-29`,
`birkin/neurosis.py:104-168`, `birkin/morpheus.py:210-350`,
`birkin/boulder.py:48-113`, `birkin/harness.py:147-177`,
`birkin/odyssey.py:20-59`, `skills/automation/odyssey/SKILL.md:89-122`).
이 구현들은 Python 상태·filesystem·scheduler·approval runtime을 직접
호출하므로 “정의만 TS”로 옮겨도 실행 guardrail은 증가하지 않는다.

`worker_hooks.py`의 taxonomy는 도입 후 한 커밋만 변경됐지만
Morpheus 구현은 반복적으로 변경됐다
(`git log --follow -- birkin/worker_hooks.py`,
`git log --follow -- birkin/morpheus.py`). 변경 빈도도 정적 taxonomy보다
실행 통합부에 집중되어 있어 TS 전환의 편익이 작다.

### 전환 조건

browser UI나 외부 SDK가 worker taxonomy를 직접 소비하기 시작하면,
TypeScript를 source of truth로 두기보다 neutral JSON Schema/manifest에서
Python과 TS binding을 생성하는 것이 적합하다. Python runtime validation은
persisted/untrusted JSON 경계 때문에 계속 유지해야 한다
(`birkin/worker_hooks.py:38-61`, `tests/test_worker_hooks.py:132-179`).

## 전체 전환 후보 순위

아래 표와 세부 분석은 구현 전 baseline을 기록한 것이다. 현재 구현 상태는
문서 상단의 **구현 상태**와 각 항목의 **구현 결과**를 기준으로 판단한다.

| 순위 | 후보 | 목표 포맷 | ROI | 권고 |
|---|---|---|---:|---|
| 1 | CurationPlan 중복 계약 | versioned JSON Schema | 5/5 | 즉시 통합 |
| 2 | `DEFAULT_CONFIG`와 loader | JSON Schema + typed normalized Python model | 4/5 | 다음 투자 |
| 3 | `cron.json` record | versioned discriminated JSON records | 4/5 | 다음 투자 |
| 4 | config 문서 | canonical schema에서 Markdown 생성 | 4/5 | config schema와 함께 |
| 5 | `SKILL.md` frontmatter | 표준 YAML parser + metadata schema | 3/5 | dual-read로 점진 전환 |
| 6 | plugin manifests | pinned published JSON Schema validation | 3/5 | 작은 CI hardening |
| 7 | executable policy tables | typed Python 유지 | 1/5 | 포맷 전환하지 않음 |

### 1. CurationPlan: 단일 versioned JSON Schema

**구현 결과:** `birkin/schemas/curation-plan-v2.schema.json`이 provider,
prompt, parser가 공유하는 canonical contract가 됐고 CurationPlan/1 입력
호환성은 유지된다.

`CURATION_PLAN_SCHEMA`는 `plan_version.const = 1`이고 op object에 annotate
필드가 없다 (`birkin/providers.py:55-81`). 계약은 v2와 `annotate`를
지원하고 prompt도 v2 출력을 요구한다
(`birkin/curation_contract.py:8-23`, `birkin/curation_prompt.py:98-122`).
Codex adapter는 이 stale schema를 native output enforcement에 전달한다
(`birkin/curation_cli.py:39-43`). 하나의 schema artifact를 provider,
deterministic validation, prompt rendering, compatibility test에서 함께
사용하면 현재 provider별 계약 차이를 제거할 수 있다.

### 2. Config: schema-backed normalized model

**구현 결과:** versioned config schema가 known-value normalization을
담당하며, sparse override와 unknown extension key는 유지된다. 영문·한글
설정 reference와 README 예제는 schema에서 생성된다.

설정은 큰 `dict[str, Any]`에 있고 saved JSON을 raw `cfg.update(saved)`로
병합한 뒤 중앙에서는 `cli_access`와 `cli_network_access`만 명시적으로
보정한다 (`birkin/config.py:22-329`, `birkin/config.py:524-572`).
타입·enum·범위·default·deprecated key를 versioned JSON Schema로 정의하고
startup에서 typed normalized config로 파싱하면 malformed value의 늦은
실패와 consumer별 cast를 줄일 수 있다.

### 3. Cron: versioned discriminated records

**구현 결과:** persisted record는 v1 discriminator와 schedule/action
variant를 검증하며, unversioned legacy records는 cron lock 안에서
idempotent하게 migration된다.

legacy daily record와 새 schedule dict가 함께 유지되고, `load_jobs()`는
저장 JSON을 record validation 없이 반환한다
(`birkin/cron.py:18-20`, `birkin/cron.py:250-255`).
`compute_next_run()`은 알 수 없는 kind를 daily로 처리하고 invalid
`next_run`은 due가 아닌 것으로 조용히 처리한다
(`birkin/cron.py:215-236`, `birkin/cron.py:400-403`).
schedule/action discriminated union과 load-time migration을 사용하면
unknown kind와 malformed timestamp를 job ID 및 JSON path와 함께 차단할 수
있다.

### 4. Config 문서 생성

README는 config block이 실제 default를 사용한다고 설명하지만
`provider`, `model`, `subagent_model` 값은 runtime default와 다르다
(`README.md:439-447`, `README.ko.md:430-438`,
`birkin/config.py:22-25`). 현재 테스트는 문서 key가 존재하는지와 두 언어의
key 집합이 같은지만 검사하며 값 일치는 검사하지 않는다
(`tests/test_readme_config.py:30-64`). config schema에서 key, type, default,
security note를 생성하면 두 README의 machine facts를 동기화할 수 있다.

### 5. Skill frontmatter: 표준 YAML과 metadata schema

현재 parser는 dependency-free YAML subset이며 parse하지 못한 구문을 raw
string으로 낮춘다 (`birkin/skills/frontmatter.py:1-13`,
`birkin/skills/frontmatter.py:93-139`). validator는 필수/권장 field와
`When to Use` section을 검사하지만 nested metadata의 구조와 YAML
정합성은 검사하지 않는다 (`birkin/skills/validate.py:73-105`).
ADR은 `SKILL.md` YAML frontmatter portability를 명시하므로 포맷 교체가
아니라 standards-compatible safe YAML parser와 versioned metadata
schema를 dual-read로 도입해야 한다 (`docs/DECISIONS.md:1025-1038`).

### 6. Plugin manifests: published schema validation

manifest는 이미 JSON이므로 포맷을 바꿀 필요가 없다
(`.claude-plugin/marketplace.json:1-13`,
`plugins/birkin-vault/.claude-plugin/plugin.json:1-14`).
현재 테스트는 일부 required field와 경로만 직접 검사한다
(`tests/test_marketplace_manifest.py:17-43`). pinned official schema
validation을 추가하고 Birkin 고유 cross-file invariant만 로컬 테스트로
유지하는 것이 작은 비용으로 install-time failure를 앞당긴다.

## 검증 영수증

- `py -3 -m compileall -q birkin`: 통과.
- workflow/worker 관련 5개 test file: **81 passed**.
- 추가 포맷 후보 관련 6개 test file: **65 passed**.
- `py -3 -m birkin --help`: 정상 출력.
- `py -3 -m birkin moirai --help`: 정상 출력.
- 격리된 `BIRKIN_HOME`에서 `birkin moirai list`: bundled 3개 로드.
- 존재하지 않는 workflow 실행: exit 1과 명시적 오류 출력.
- 격리된 `BIRKIN_HOME`에서 `birkin skills validate --verbose`:
  **56 clean, 0 warnings, 0 errors**.
- runtime driver에서 CurationPlan은
  `schema_version=1`, `contract_version=2`,
  `schema_has_annotate=False`, `contract_has_annotate=True`로 재현됨.
- runtime driver에서 worker contract는 8개 worker, Mnemosyne no-model,
  Osiris-to-Boulder persistence owner로 출력됨.

## 권장 실행 순서

1. CurationPlan v2 JSON Schema를 canonical artifact로 만들고 provider,
   prompt, parser, compatibility tests를 연결한다.
2. config JSON Schema와 normalized typed model을 warning mode로 도입하고,
   같은 schema에서 영어/한국어 config reference를 생성한다.
3. `cron.json`에 schema version을 추가하고 discriminated record로 한 번
   migration한다.
4. skill frontmatter를 strict/legacy dual-read로 비교한 뒤 strict parser로
   전환한다.
5. plugin manifest CI를 published schema validation으로 교체한다.
6. TS 공유 consumer가 생기기 전에는 executable workflow/worker를
   Python에 유지한다.
