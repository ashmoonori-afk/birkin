<div align="center">

<img src="./docs/assets/birkin-hero-courier.png" alt="전령을 앞지르는 구조화된 로컬 에이전트 Birkin" width="820" />

# birkin

### 로컬 메모리. 결정적 제어. 사람의 권한.

메모리, 실행, 자기개선을 내 컴퓨터에서 직접 확인할 수 있는 의존성 가벼운 파이썬 에이전트.

[![Tests](https://github.com/ashmoonori-afk/birkin/actions/workflows/tests.yml/badge.svg)](https://github.com/ashmoonori-afk/birkin/actions/workflows/tests.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](./pyproject.toml)
[![VS Code](https://img.shields.io/badge/VS_Code-official_extension-007ACC?logo=visualstudiocode&logoColor=white)](./vscode-extension)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

[존재 이유](#왜-birkin인가) · [빠른 시작](#빠른-시작) · [GitHub Action](#github-action) · [Sandbox](#격리-실행) · [VS Code](#vs-code-extension) · [비교](#표면-비교) · [아키텍처](#아키텍처) · [명령어](#명령어) · [English](./README.md)

</div>

---

## 왜 birkin인가?

에이전트 런타임은 시연하기는 쉽지만 신뢰하기는 어렵습니다. Birkin은 모델의 유용함은 유지하고 권한은 코드로 옮깁니다.

| 문제 | Birkin의 해법 |
|---|---|
| 메모리가 호스팅 서비스나 벡터 데이터베이스 안으로 사라짐 | YAML frontmatter와 wikilink를 쓰는 마크다운 노트를 Obsidian 호환 로컬 볼트에 저장합니다. |
| 프롬프트가 자기 자신의 안전을 강제해야 함 | 네이티브 도구는 하나의 registry를 지나며, shell과 예약 작업은 결정적 정책과 승인 큐를 통과합니다. |
| “멀티에이전트”가 모델의 재귀적 자기 spawn을 뜻함 | Moirai가 budget·spawn 상한과 함께 파이썬 소유의 `agent`, `parallel`, `pipeline` 그래프 primitive를 제공합니다. |
| 자기개선이 런타임을 몰래 변경함 | Harness가 타입화된 proposal을 버전 ledger에 기록하고 rollback을 지원합니다. |
| 코딩 에이전트가 사용자가 plan을 이해하기 전에 파일을 변경함 | 공식 VS Code extension이 editor context를 보내고, plan을 먼저 검토하며, 제안 diff를 표시하고, Birkin 승인을 처리하고, checkpoint를 복원합니다. |
| 로컬 도구가 불투명한 서비스가 됨 | run, approval, checkpoint, status, config가 모두 로컬에서 확인 가능합니다. |

Birkin 핵심 런타임에는 **필수 서드파티 파이썬 의존성이 없습니다**. 선택적 extra가 voice, desktop vision, office 파일 지원을 추가합니다. 현재 저장소에는 **56개 스킬**이 번들되며, 기본 테스트는 모두 오프라인 실행을 목표로 합니다.

## 메모리

Hangul/jamo 인식 tokenization을 사용하는 BM25가 추가 package 없는 기본 retrieval engine입니다. 모든 결과는 정규화된 `lexical`, `vector`, `entity`, `time` score와 결과를 만든 signal, 각 backend 이름을 공개합니다. Vector embedding, 1-hop entity traversal, temporal reranking은 서로 독립적인 opt-in입니다.

```bash
python -m pip install -e ".[memory-semantic]"  # 로컬 sentence-transformers 전용
```

```json
{
  "memory_vector_enabled": true,
  "memory_entity_enabled": true,
  "memory_temporal_enabled": true
}
```

Markdown가 계속 source of truth입니다. Entity graph는 title, tag, `[[wikilink]]`에서 다시 만들 수 있으며 lexical search에 graph sidecar가 필요하지 않습니다. Temporal fact는 `valid_at`(사실이 된 시점), `invalid_at`(더 이상 사실이 아닌 시점), `expired_at`(잘못임을 알게 된 시점)을 분리하고 선택적으로 `supersedes` link를 둡니다. Search는 `as_of`, `since`, `until` date filter를 받습니다.

메모리 소유 범위는 `user`, `organization`, `project`, `agent`, `workflow`입니다. User 메모리는 기존 vault layout을 그대로 사용하고, 나머지 root는 `.birkin-scopes/<scope>`에 있으며 내부에서는 같은 zone layout을 유지합니다. 같은 key는 가장 구체적인 순서인 **workflow > agent > project > organization > user**로 resolve됩니다. `memory_visible_scopes`는 읽을 수 없는 root를 fail closed로 차단하고, `memory_source_trust`, `memory_default_trust`, query의 `min_trust`가 source filtering을 제어합니다. Search hit는 `scope`, `record_source`, `trust`를 공개합니다. Owner가 note를 `shared_read_only`로 표시하면 볼 수 있는 agent는 owner label과 함께 읽을 수 있지만 non-owner write는 typed policy error로 거부됩니다.

Commit된 14-question LongMemEval fixture는 retrieval과 final-answer stage를 분리해 보고합니다. 네 configuration 모두 retrieval recall `1.000`, answer accuracy `0.857`(query당 context token 11.9-12.4)이었으므로 retrieval 뒤 context assembly gap이 숨지 않습니다. Category·cost table과 public dataset 정확한 실행 명령은 [benchmark 결과](./benchmarks/RESULTS.md)에 있습니다. 이 값은 fixture 결과이며 public leaderboard 결과가 아닙니다.

## 빠른 시작

Python 3.10 이상이 필요합니다. 기본 provider는 로컬 인증된 Codex CLI이며, setup에서 Claude CLI나 API provider를 고를 수 있습니다.

```bash
git clone https://github.com/ashmoonori-afk/birkin.git
cd birkin
python -m pip install -e .
birkin setup
birkin chat
```

로컬 서비스 표면은 별도 터미널에서 실행합니다.

```bash
birkin gateway          # 127.0.0.1:8788 로컬 HTTP, Telegram은 선택 사항
birkin web --no-browser # 127.0.0.1:8787 dashboard/control API
```

선택 기능은 명시적으로 설치합니다.

```bash
python -m pip install -e ".[memory-semantic]"
python -m pip install -e ".[voice]"
python -m pip install -e ".[desktop]"
python -m pip install -e ".[office]"
python -m pip install -e ".[full]"
```

> [!IMPORTANT]
> 네이티브 도구는 현재 OS 계정 권한으로 실행됩니다. gateway를 loopback 전용으로 유지하고, 배포 환경에 맞게 `shell_approval`, `fs_jail`, disabled tools, channel allowlist를 설정하며, 결과가 생기는 행동은 승인 전에 검토하십시오.

## GitHub Action

공식 composite Action은 신뢰된 issue 또는 pull request comment를 격리된 Birkin job으로 바꿉니다. 소비자 repository의 `.github/workflows/birkin.yml`에 아래 workflow를 넣고 Actions secret으로 `ANTHROPIC_API_KEY`를 추가하십시오. 사용할 버전을 정한 뒤 `@main`은 release tag나 commit SHA로 고정하십시오.

```yaml
name: Birkin
on:
  issue_comment:
    types: [created]
permissions:
  contents: read
jobs:
  birkin:
    if: >-
      startsWith(github.event.comment.body, '/birkin') &&
      contains(fromJSON('["OWNER","MEMBER","COLLABORATOR"]'),
      github.event.comment.author_association)
    runs-on: ubuntu-latest
    permissions:
      contents: write
      issues: write
      pull-requests: write
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262
        with:
          ref: ${{ github.event.repository.default_branch }}
          persist-credentials: false
      - uses: ashmoonori-afk/birkin@main
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          test-command: python -m pytest -q
          max-retries: "1"
```

신뢰된 maintainer가 issue나 PR에 `/birkin <task>`를 comment하면 Birkin은 default branch에서 작업 branch를 만들고 설정된 test command를 실행합니다. 실패하면 정확한 출력으로 제한된 횟수만큼 수정한 뒤 push하고 원본 issue/PR을 참조하는 PR을 엽니다. PR에서 `/birkin review <focus>`를 사용하면 도구 없는 model call로 diff를 읽고 구조화된 review comment를 게시하며 PR 코드는 실행하지 않습니다.

> [!CAUTION]
> 이 workflow는 secret을 가진 fork checkout 대신 `issue_comment`를 사용합니다. 실행 주체를 `OWNER`, `MEMBER`, `COLLABORATOR`로 제한하고, 신뢰된 default branch만 checkout하며, workflow 전체는 read-only이고 job에는 필요한 세 write scope만 선언합니다. Credential은 문서화된 `github-token`, `anthropic-api-key`, `openai-api-key` input으로만 받습니다. Driver는 task나 diff를 처리하기 전에 agent tool과 test subprocess 환경에서 이 값을 제거합니다. Secret을 가진 채 신뢰되지 않은 코드를 checkout하는 형태로 바꾸지 마십시오.

## 격리 실행

Birkin은 선언된 repository job을 일회용 **git worktree** 또는 **Docker container**에서 실행할 수 있습니다. 두 backend 모두 동일한 불변 `SandboxPolicy`를 사용하며, GitHub Action worker도 별도의 remote policy 대신 local 실행과 같은 evaluator를 호출합니다.

재현 가능한 setup을 위해 `.birkin/sandbox.json`을 commit합니다.

```jsonc
{
  "backend": "docker",
  "image": "python:3.12.4-slim@sha256:<digest>",
  "setup": ["python -m pip install -e ."],
  "env_allowlist": ["PIP_INDEX_URL"],
  "network": "allowlist",
  "network_allowlist": ["pypi.org"],
  "write_paths": ["birkin", "tests"]
}
```

- **Network:** `off`는 모든 선언 destination을 거부하고 Docker에 `--network=none`을 추가합니다. `allowlist`는 repository에 명시되지 않은 destination을 거부합니다.
- **Secret:** child는 `env_allowlist`에 이름이 있는 변수만 받습니다. 상속 credential과 그 밖의 host 변수는 모두 제거됩니다.
- **Write:** Docker는 repository를 read-only로 mount하고 설정된 path만 writable overlay로 추가합니다. Worktree job은 분리된 일회용 checkout에서 실행되고 실제 변경을 같은 scope로 검증하며 실패 후에도 checkout을 삭제합니다.

Policy 또는 config 위반은 typed error로 delivery 전에 실패합니다. Setup command는 매 job마다 선언 순서대로 실행됩니다. Docker image는 digest로 고정하고 writable path는 repository에 미리 만들어 두십시오. Worktree backend는 일회용 repository/write 격리를 제공하지만 network namespace는 제공하지 않으므로 kernel 수준 network 격리가 필요하면 Docker를 사용하십시오.

## Browser QA

선택적 browser surface와 Chromium runtime을 설치합니다. Core Birkin은 Playwright를 import하지 않습니다.

```bash
python -m pip install 'birkin[browser]'
python -m playwright install chromium
```

Native registry는 `browser_navigate`, `browser_click`, `browser_fill`, `browser_press`, `browser_execute`, `browser_screenshot`, `browser_evidence`, `browser_close`를 제공합니다. 이 도구들은 하나의 page를 공유하므로 agent는 web code를 수정한 뒤 source에서 결과를 추측하지 않고 실제 rendering을 검증할 수 있습니다.

Browser traffic은 repository의 `sandbox.network`와 `sandbox.network_allowlist` 정책을 그대로 재사용합니다. 기본값 `network: "off"`는 fail closed합니다. Local WebUI QA에는 `network`를 `allowlist`로 설정하고 `127.0.0.1`을 포함하며 screenshot path를 `sandbox.write_paths` 안에 둡니다. 모든 navigation과 page subrequest가 검사되므로 redirect, script, `fetch`, click으로 발생한 request도 allowlist를 우회하지 못합니다. Registry hook, `disabled_tools`, approval replay도 모든 native tool과 동일한 gate를 유지합니다. 정책 거부는 `BrowserPolicyViolation` error로 반환됩니다.

Birkin 자체 WebUI를 대상으로 실행할 수 있는 ouroboros 검증 절차는 다음과 같습니다.

1. `birkin/web/static/index.html`을 수정한 뒤 `birkin web --no-browser`를 시작하고 private bootstrap URL을 복사합니다.
2. `sandbox.network="allowlist"`, `sandbox.network_allowlist=["127.0.0.1"]`로 설정한 Birkin native session에서 해당 URL로 `browser_navigate`를 호출합니다.
3. `#lens-toggle`로 `browser_click`을 호출하고 `artifacts/webui.png` 같은 이름 있는 상대 path로 `browser_screenshot`을 호출합니다.
4. `browser_evidence`를 호출해 console 및 request/response summary를 screenshot과 함께 저장합니다. 마지막에는 `browser_close`로 Chromium과 모든 context를 종료합니다.
5. Negative proof로 allowlist에 없는 host로 navigate하고 typed refusal을 보관합니다. 이 request는 network에 도달하면 안 됩니다.

이는 HTML parser가 아니라 실제 browser 실행입니다. Form에는 `browser_fill`/`browser_press`, 집중된 page-state assertion에는 `browser_execute`를 사용합니다. 특정 surface에서 action을 노출하지 않으려면 `disabled_tools`에서 이름별로 비활성화합니다.

## VS Code extension

`vscode-extension/`은 공식 TypeScript extension입니다. 두 번째 에이전트 프로토콜을 만들지 않고 Birkin의 기존 로컬 표면에 연결됩니다.

- 활성 selection, range, workspace, 열린 파일 descriptor를 gateway에 전달
- 실행하지 않는 plan을 요청하고 명시적인 **Execute Plan** 결정 요구
- 파일 proposal을 VS Code 네이티브 inline diff editor로 표시
- 기존 Birkin approval queue를 통해 승인 또는 거절
- 확인 후 Birkin shadow-git checkpoint 복원
- status bar에 실시간 runtime·검토 대기 상태 표시

### 소스에서 설치

```bash
cd vscode-extension
npm ci
npm run compile
npm run package
code --install-extension birkin-vscode-0.1.0.vsix
```

Extension Development Host로 실행:

```bash
cd vscode-extension
npm ci
npm run compile
code --extensionDevelopmentPath="$PWD"
```

`birkin gateway`와 `birkin web --no-browser`를 모두 시작하십시오. WebUI는 private `~/.birkin/web_session.json`을 쓰며 extension은 이 파일에서 loopback port와 capability를 찾습니다. gateway가 8788이 아니면 `birkin.gatewayUrl`을 바꾸십시오. `BIRKIN_HTTP_TOKEN`을 설정했다면 같은 값을 `birkin.gatewayToken`에 넣으십시오.

Command Palette에서 **Birkin: Review Plan Before Execution**을 실행하십시오. 나머지 명령은 context 요청 전송, 제안 변경 검토, 파일 rollback, status 갱신을 담당합니다.

## 표면 비교

아래 행은 모두 이 저장소에 실제로 포함된 표면을 설명합니다.

| 기능 | CLI / REPL | Gateway | WebUI | VS Code |
|---|:---:|:---:|:---:|:---:|
| 대화형 에이전트 | 지원 | 지원 | 미지원(모니터링/control) | Gateway를 통해 지원 |
| 현재 editor selection과 열린 파일 | 수동 | 수동 | 미지원 | 지원 |
| 실행 전 plan review | slash command/workflow에 따라 다름 | 대화에 따라 다름 | 미지원 | 전용 review surface |
| 제안 변경 diff | 터미널 checkpoint diff | 미지원 | approval 상세 | VS Code 네이티브 diff editor |
| Approval queue | `birkin review` | 신뢰 chat control | 승인/거절 API와 UI | 승인/거절 API |
| 파일 rollback | `/rollback` | 미지원 | checkpoint control API | checkpoint picker |
| 실시간 status | status line | progress callback | dashboard | status bar |
| 로컬 transport | process stdin/stdout | loopback HTTP / channel | loopback HTTP | 기존 gateway + WebUI API |

## 아키텍처

모델은 제안하고, 결정적 코드는 영속화·정책·권한을 소유합니다.

```mermaid
flowchart LR
    U[CLI · Gateway · VS Code] --> P[promptgate.py]
    P --> A[Agent loop]
    A --> R[ToolRegistry]
    R --> G{Policy gates}
    G -->|safe| T[Native tools]
    G -->|consequential| Q[Approval queue]
    Q -->|human approves| T
    T --> C[Checkpoint + audit records]
    A --> M[Markdown memory]
    A --> W[Moirai graph runtime]
```

<details>
<summary><strong>저장소 구조</strong></summary>

```text
birkin/
  agent.py          네이티브 tool loop, steering, compaction, 병렬 호출
  runtime.py        provider, prompt, registry, memory, skill 구성
  promptgate.py     모든 main surface의 단일 system-prompt 조립 지점
  tools/            file, shell, web, vision, memory, session, subagent
  approvals.py      사람의 gate와 승인된 action 실행
  checkpoints.py    외부 shadow-git snapshot과 restore
  gateway/          local HTTP, Telegram, outbound channel adapter
  web/              local dashboard와 인증된 control API
  harness.py        검증되는 자기개선 ledger와 rollback
  moirai/           결정적 멀티에이전트 graph runtime
  mcp_server.py     memory, skill, proposal용 stdio MCP server
vscode-extension/   공식 strict-TypeScript editor integration
skills/             번들 Markdown skill
tests/              offline unit, integration, end-to-end coverage
```

상태는 `BIRKIN_HOME`(보통 `~/.birkin`) 아래 파일에 저장됩니다. Dashboard는 process별 capability를 사용합니다. Gateway는 loopback에 bind하며 추가로 `BIRKIN_HTTP_TOKEN`을 요구할 수 있습니다. MCP는 stdio 위 newline-delimited JSON-RPC를 사용합니다. VS Code extension은 이 기존 권한에 연결됩니다. turn은 gateway `/message`, approval·status·editor context·checkpoint는 WebUI endpoint를 사용합니다.

</details>

## Checkpoint

WebUI workbench는 Birkin의 외부 shadow-git snapshot을 tool 단위 timeline으로
표시합니다. 각 항목은 tool, 시간, 변경 경로, 결과, 그리고 실행 전후 상태를
담은 checkpoint hash를 기록합니다. 어떤 checkpoint든 열어 변경 전에 전체
patch와 파일별 patch를 미리 볼 수 있습니다.

| Restore mode | Workspace 파일 | Task/대화 상태 |
|---|---:|---:|
| `files` | 복원 | 유지 |
| `task` | 유지 | 복원 |
| `both` | 복원 | 복원 |

모든 restore는 파괴적 작업이므로 WebUI는 기존 human approval authority에
요청을 queue하고 현재 상태를 먼저 보호합니다. 대안 시도는 선택한
checkpoint에서 일회용 policy-controlled sandbox worktree를 만들고 lineage를
기록하므로 현재 workspace를 변경하지 않습니다. 인증 API도 checkpoint 목록,
`/timeline`, `/lineage`, `/{id}/diff`, `/{id}/restore`, `/{id}/fork`로 같은
흐름을 제공합니다.

<details>
<summary><strong>실행과 복구 경로</strong></summary>

1. `runtime.py`가 설정된 provider, memory, skill, hook, checkpoint manager, native tool registry를 구성합니다.
2. `promptgate.py`가 REPL, gateway, dry-run, warm session이 공유하는 sealed main prompt를 조립합니다.
3. `ToolRegistry.run`이 hook, redaction, output 처리의 네이티브 통제 지점입니다.
4. 결과가 생기는 cron, shell, operation, workflow, harness action은 file-backed approval record가 됩니다.
5. 파일을 변경하는 도구는 mutation 전에 프로젝트를 Birkin 외부 checkpoint store에 snapshot합니다.
6. 사용자는 CLI, 신뢰 channel, WebUI, VS Code에서 queue를 처리합니다. Rollback은 현재 상태를 먼저 보호한 뒤 선택한 checkpoint를 복원합니다.

</details>

## Working Memory

Birkin은 현재 작업 계약을 first-class **Working Memory**로 유지합니다. 이는
대화 transcript나 장기 semantic memory가 아닙니다. 한 세션의 목표, 사용자
교정, 제약, 결정, 미완료 항목, 증거, 다음 행동을 담는 작고 구조화된
상태입니다.

각 agent turn은 기존 session-local harness journal인
`$BIRKIN_HOME/sessions/<session>/harness/harness_state.json`을
Prompt-Gate를 통해 다시 읽습니다. 따라서 context compaction이 이 상태를
요약해 없앨 수 없고, 동일한 안정적 session ID로 process를 재개하면 같은
상태를 복구합니다. Objective와 completion verifier는 계속 `goals.py`가
canonical하게 소유하고, harness journal은 교정·제약·결정·미완료 항목·
증거·다음 행동을 소유합니다. Update는 lock 안에서 atomic replace로
저장됩니다. 반복된 목록 값은 deduplicate되고 새 `--goal`은 해당 session의
이전 목표를 교체합니다.

```bash
birkin working-memory update \
  --session issue-123 \
  --goal "수정 사항 배포" \
  --correction "공개 JSON 형상을 유지" \
  --constraint "오프라인 유지" \
  --decision "기존 atomic store 사용" \
  --incomplete "보안 regression 실행" \
  --evidence "집중 테스트 통과" \
  --next-action "전체 suite 실행"

birkin working-memory show --session issue-123 --json
birkin working-memory clear --session issue-123
```

목록 값 flag는 반복해서 지정할 수 있습니다. Session ID는 path-safe하게
제한됩니다. 첫 글자는 영문자나 숫자여야 하며 전체 길이는 1-128자, 허용
문자는 ASCII 영문자, 숫자, `.`, `_`, `-`입니다. 전체 표면은
`birkin working-memory --help`로 확인하십시오.

## 명령어

| 명령 | 용도 |
|---|---|
| `birkin setup` | Provider와 workspace 안내 설정. |
| `birkin chat` | 대화형 로컬 에이전트(기본 명령). |
| `birkin gateway` | Loopback HTTP와 설정된 message channel 실행. |
| `birkin web [--no-browser]` | 로컬 dashboard와 인증된 control API 실행. |
| `birkin review` | 결과가 생기는 대기 action 승인 또는 거절. |
| `birkin permission` | Approval category와 CLI access 확인·변경. |
| `birkin tools` | 네이티브 tool 목록·활성화·비활성화. |
| `birkin model` / `birkin models` | Model 확인 또는 선택. |
| `birkin skills` | Skill 목록·조회·sync·validate·관리. |
| `birkin daemon` | Morpheus + cron scheduler 실행 또는 설치. |
| `birkin morpheus [--dry-run]` | 예약 자기개선 routine 즉시 실행. |
| `birkin harness` | 개선 ledger 조회·refine·export·rollback. |
| `birkin moirai` | 결정적 workflow 목록·실행·조회·resume. |
| `birkin runs` / `birkin trace ID` | Run summary와 상세 audit record 조회. |
| `birkin cron` | 예약 job 목록 또는 삭제. |
| `birkin sessions` | 저장된 대화 목록 또는 export. |
| `birkin working-memory` | 구조화된 현재 작업 상태 조회·갱신·삭제. |
| `birkin mcp-serve` | Birkin memory, skill, proposal을 MCP stdio로 제공. |
| `birkin voice` | 선택적 voice daemon 설정·제어. |

전체 interface는 `birkin --help` 또는 `birkin <command> --help`로 확인하십시오.

## 설정

`birkin setup`은 `~/.birkin/config.json`을 씁니다. 아래 블록은 `birkin.config.DEFAULT_CONFIG`에서 생성되고 테스트가 검증하므로, 발췌가 아니라 전체 기본값입니다.

<details>
<summary><strong>전체 기본 설정</strong></summary>

<!-- config-schema:start -->
```json
{
  "provider": "codex-cli",
  "model": "default",
  "subagent_model": "default",
  "base_url": "",
  "cli_command": [],
  "api_key": null,
  "max_tokens": 4096,
  "temperature": 1.0,
  "max_turns": 24,
  "auto_compact": true,
  "context_window": 200000,
  "fallback_provider": "",
  "fallback_model": "",
  "fallback_base_url": "",
  "fallback_cooldown": 300,
  "api_keys": [],
  "a2a_enabled": false,
  "lsp_servers": {},
  "spill_threshold": 30000,
  "spill_dir": "",
  "spill_retention_days": 7,
  "redact_secrets": true,
  "repl_typed_line": "steer",
  "moirai_auto": false,
  "moirai_workers": 4,
  "moirai_max_agents": 100,
  "moirai_roles": {},
  "moirai_token_budget": 0,
  "marginalia_api_key": "",
  "parallel_tools": true,
  "parallel_tool_workers": 8,
  "shell_approval": "manual",
  "checkpoints": true,
  "hooks": {},
  "hooks_auto_accept": false,
  "skills_guard_agent_created": false,
  "checkpoint_keep": 20,
  "command_allowlist": [],
  "approval_model": "",
  "max_depth": 2,
  "extra_skill_dirs": [],
  "disabled_tools": [],
  "desktop_tools": false,
  "self_improve": true,
  "skill_nudge_interval": 3,
  "memory_nudge_interval": 6,
  "web_port": 8787,
  "gateway_port": 8788,
  "gateway_model": "",
  "gateway_reasoning_effort": "",
  "gateway_persistent": true,
  "gateway_allowed_tools": [],
  "repl_warm_session": false,
  "gateway_clean_hooks": true,
  "gateway_thinking_tokens": 0,
  "gateway_prewarm": true,
  "voice": {
    "wake_phrase": "Daddy is home",
    "gateway_url": "",
    "session_id": "voice-local",
    "sample_rate": 24000,
    "stt_model": "gpt-transcribe",
    "tts_model": "gpt-4o-mini-tts",
    "tts_voice": "coral",
    "tts_instructions": "Speak concisely and clearly.",
    "conversation_style": "",
    "onboarding_complete": false,
    "background_workers": 2
  },
  "autosave_transcripts": false,
  "autosave_redact_secrets": true,
  "autosave_max_chars": 4000,
  "autosave_max_turns": 40,
  "autosave_retention_days": 30,
  "autosave_max_files": 500,
  "neurosis_threshold": null,
  "neurosis_auto": true,
  "channels": {
    "http": {
      "enabled": true
    },
    "telegram": {
      "enabled": false,
      "token": "",
      "allowed_chat_ids": [],
      "stream": true
    },
    "slack": {
      "enabled": false,
      "webhook_url": ""
    },
    "discord": {
      "enabled": false,
      "webhook_url": ""
    }
  },
  "vault_path": "",
  "memory_vector_enabled": false,
  "memory_vector_backend": "sentence-transformers",
  "memory_vector_model": "all-MiniLM-L6-v2",
  "memory_entity_enabled": false,
  "memory_temporal_enabled": false,
  "memory_scope": "user",
  "memory_visible_scopes": [
    "workflow",
    "agent",
    "project",
    "organization",
    "user"
  ],
  "memory_default_trust": "medium",
  "memory_source_trust": {},
  "morpheus_deliver_chat_id": "",
  "workspace_roots": [],
  "reaper_enabled": true,
  "morpheus_provider": "",
  "morpheus_model": "",
  "morpheus_hour": 7,
  "morpheus_minute": 0,
  "auto_approve": [
    "memory",
    "skill"
  ],
  "harness_enabled": true,
  "harness_turn_interval": 12,
  "harness_cooldown_min": 15,
  "harness_compact_review": true,
  "harness_max_edits": 12,
  "harness_prompt_budget": 20000,
  "harness_auto_approve": [
    "memory",
    "skill_note"
  ],
  "cli_access": "workspace",
  "cli_network_access": false,
  "egress": {
    "enabled": true,
    "enforced": true,
    "max_bytes": 1048576,
    "destinations": {}
  },
  "allow_unattended_full": false,
  "budget_tokens_daily": 0,
  "budget_tokens_monthly": 0,
  "subagent_tree_max_tokens": 0,
  "subagent_tree_max_usd": 0.0,
  "subagent_tree_deadline_seconds": 0,
  "subagent_tree_max_concurrent": 4,
  "subagent_tree_max_nodes": 16,
  "cli_timeout": 300,
  "evidence_required": false,
  "critique_agents": 3,
  "boulder_max_iters": 100,
  "fs_jail": false,
  "sandbox": {
    "backend": "worktree",
    "image": "",
    "setup": [],
    "env_allowlist": [],
    "network": "off",
    "network_allowlist": [],
    "write_paths": [
      "."
    ]
  },
  "update_verify_signature": false
}
```
<!-- config-schema:end -->

</details>

Provider secret은 환경 변수에 두는 것이 원칙입니다. `api_keys`는 환경 변수 pool의 이름이며 raw key를 붙여 넣는 곳이 아닙니다. `a2a_enabled`는 opt-in입니다. Enforced egress는 검사되지 않은 네이티브 network 경로를 비활성화하고 설정된 destination만 Birkin의 inspected tool을 통해 허용합니다. Sandbox 안의 gateway child는 `propose_action`으로 shell 요청을 제출할 수 있고, Birkin은 이를 child sandbox에서 실행하지 않고 승인 큐에 넣습니다.

## 개발

```bash
python -m pip install -e ".[dev]"
python -m compileall -q birkin
python -m pytest

cd vscode-extension
npm ci
npm test
npm run compile
npm run test:e2e
```

CI는 Ubuntu/Python 3.10, macOS/Python 3.13, Windows/Python 3.13에서 파이썬 suite를 실행합니다. Extension unit test는 Vitest, 실제 host QA는 `@vscode/test-electron`을 사용합니다.

## 라이선스

[MIT](./LICENSE). Attribution은 [NOTICE](./NOTICE)를 참고하십시오.
