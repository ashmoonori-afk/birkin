# birkin

**메모리, 실행, 자기개선을 검토 가능한 로컬 상태로 다루는 무의존성 Python
에이전트입니다.**

birkin은 로컬 우선 CLI 에이전트이자 HTTP/Telegram 게이트웨이, MCP 서버,
멀티에이전트 런타임입니다. 배포 패키지는 Python 표준 라이브러리만 사용합니다.
저장소는 약 32,000줄의 Python 코드, 2,000개 이상의 오프라인 테스트, 56개의
번들 스킬로 구성됩니다.

핵심은 또 하나의 채팅 루프가 아닙니다. 재개 가능한 목표, 격리된 서브에이전트,
워크스페이스 체크포인트, 비밀값 마스킹, 모델 장애조치, 투명한 Markdown 메모리,
결정론적 멀티에이전트 워크플로, 되돌릴 수 있는 자기개선 원장을 하나의 작은
런타임에 결합한 방식이 특징입니다.

[English](./README.md)

## birkin이 존재하는 이유

이미 훌륭한 범용 에이전트 프로젝트가 많습니다. birkin은 다른 선택을 합니다.

- 다중 언어 런타임 대신 설치 가능한 Python 패키지 하나
- SDK 중심 공급자 스택 대신 필수 런타임 의존성 0개
- 불투명한 호스팅 상태 대신 보이는 파일과 추가 전용 기록
- 브라우저/컴퓨터 자동화 대신 작고 명시적인 네이티브 도구 표면
- 실행 경로의 승인, 체크포인트, 마스킹 관문
- 검토하고 되돌릴 수 있는 제안으로서의 지속적 자기개선

그 결과 일반적인 Python 도구만으로 감사, 임베딩, 오프라인 테스트, 복구가
유난히 쉽습니다.

## 코드 기준 비교

아래 비교는 2026-08-10에 확인한 birkin 코드와
[hermes-agent](https://github.com/NousResearch/hermes-agent),
[prime-agent](https://github.com/PrimeIntellect-ai/prime-agent)의 현재 소스
트리를 기준으로 합니다. 제품 홍보 문구나 설계문서는 근거로 사용하지 않았습니다.

| | birkin | hermes-agent | prime-agent |
|---|---|---|---|
| 주 구조 | Python 패키지 하나 | 대형 Python 앱 + JS/TS 표면 | TypeScript 모노레포 + Python 커널 shim |
| 대략적 소스 규모 | Python 32K LOC | Python 166K + JS/TS 132K LOC | TypeScript 152K LOC |
| 필수 런타임 의존성 | 0 | 다수의 정확히 고정된 Python 패키지 + extras | 여러 npm 패키지 의존성 그래프, Python runtime은 IPython 사용 |
| 에이전트/도구 구성 | 네이티브 루프 하나와 registry 관문 하나 | 광범위한 provider, gateway, browser, media, tool 하위 시스템 | `ai`, `agent`, `coding-agent`, `tui` 계층 패키지 |
| 메모리 | 편집 가능한 Markdown/YAML/wikilink vault | 여러 상태 및 메모리 통합 | 세션/context-tree 중심 |
| 자기개선 | 검증과 롤백이 있는 버전 제안 원장 | 광범위한 스킬 및 런타임 생태계 | 확장 및 패키지 생태계 |
| UI/채널 폭 | CLI, WebUI, 로컬 HTTP, Telegram, MCP, A2A | 훨씬 넓은 브라우저, gateway, 메시징 표면 | 풍부한 터미널 UI와 coding-agent 확장 |
| 가장 잘 맞는 용도 | 작고 감사 가능한 장기 실행 로컬 에이전트 | 기능 폭과 많은 통합 | TypeScript 기반 coding-agent 플랫폼과 TUI |

### birkin이 더 강한 부분

**작은 의존성과 공급망 표면.** `pyproject.toml`의 런타임 의존성은 0개입니다.
HTTP, streaming, JSON-RPC, cron parsing, persistence, provider client,
네이티브 agent loop가 패키지 안에 구현되어 있습니다. 선택적 데스크톱
스크린샷만 명시적으로 켰을 때 Pillow와 pywin32를 사용합니다.

**도구 결과를 위한 단일 강제 경로.** 모든 네이티브 도구 호출은
`ToolRegistry.run`을 통과합니다. 여기서 hook이 관찰하고, 텍스트 결과를
마스킹하며, 마스킹 이후에만 큰 텍스트를 별도 파일로 넘깁니다. 이미지 바이트는
이벤트 payload와 spill 파일에 들어가지 않습니다. agent loop에는 하나의 typed
`ToolResult` 형태만 전달됩니다.

**자기개선은 보이지 않는 변이가 아니라 데이터입니다.** `harness.py`는 typed
proposal을 받고, 한도를 검증하며, prompt/memory/skill/config 편집을 원장에
기록하고 롤백을 지원합니다. `morpheus.py`는 agent를 직접 덮어쓰지 않고 최근
작업에서 proposal을 만듭니다. 같은 harness를 turn 경계에서도 실행할 수 있습니다.

**투명한 메모리.** `memory.py`는 YAML frontmatter가 있는 Markdown note와
wikilink를 Obsidian 호환 vault에 저장합니다. `mnemosyne.py`는 LLM 없는 index,
zone, priority, decay를 제공합니다. vector database나 migration 도구 없이도
사용자가 지식 기반을 직접 읽고 수정할 수 있습니다.

**계층적인 장애 대응.** Provider 호출은 retry하고, rate limit 뒤 credential을
회전하며, 다른 provider로 failover할 수 있습니다. 긴 대화는 자동 compact되고,
workspace 편집에는 checkpoint를 만들 수 있습니다. 목표 실행은 중단 없는 단일
프로세스에 기대지 않고 재개 가능한 Boulder plan을 저장합니다.

**하나의 prompt 조립 관문.** `promptgate.py`가 모든 표면의 persona, memory,
skill, runtime notice를 조립합니다. REPL, gateway, dry-run, warm session이 서로
다른 system prompt를 만들지 않습니다.

**두 번째 런타임 없는 멀티에이전트 작업.** 격리된 subagent, 병렬 read-only
tool batch, 결정론적 Moirai workflow, A2A JSON-RPC, MCP가 같은 패키지와 저장
규칙을 사용합니다.

### hermes-agent와 prime-agent가 더 강한 부분

birkin은 의도적으로 표면적이 더 작습니다.

- hermes-agent는 훨씬 많은 gateway platform, browser/computer-use 코드,
  provider adapter, media tool, 배포 통합을 갖습니다.
- prime-agent는 더 풍부한 TypeScript 패키지 생태계, terminal UI, extension
  surface, browser용 build target, IPython 기반 coding runtime을 갖습니다.
- birkin에는 네이티브 browser automation과 두 프로젝트의 완전한 TUI stack에
  해당하는 기능이 없습니다.
- birkin은 주로 단일 프로세스 로컬 런타임이며 분산 control plane이 아닙니다.
- 네이티브 도구는 현재 사용자의 권한으로 실행됩니다. 배포 시 `shell_approval`,
  `fs_jail`, disabled tool, gateway 인증, allowlist를 직접 설정해야 합니다.

통합 폭보다 작은 크기, 로컬 검토 가능성, 되돌릴 수 있는 운영이 중요할 때
birkin이 잘 맞습니다.

## 구조

```text
birkin/
  agent.py          네이티브 tool-calling loop, compaction, 병렬 호출
  llm.py            provider protocol, streaming, retry/failover 경계
  runtime.py        client, prompt, registry, memory, skill 조립
  promptgate.py     유일한 system-prompt 조립 지점
  tools/            file, shell, web, vision, session, memory, subagent
  gateway/          로컬 HTTP 및 Telegram channel
  memory.py         Obsidian 호환 semantic memory
  mnemosyne.py      기계적 memory index, zone, decay
  harness.py        검증된 자기개선 원장과 rollback
  morpheus.py       예약된 proposal 생성
  moirai/           결정론적 multi-agent workflow engine
  boulder.py        영속적인 재개 가능 goal plan
  checkpoints.py    workspace snapshot과 복원
  shellguard.py     파괴적 command 승인
  security.py       배포용 security 진단
  a2a/              Agent2Agent JSON-RPC server
  web/              로컬 WebUI server
skills/             56개 번들 Markdown skill
tests/              offline unit, integration, gateway, e2e coverage
```

구조는 의도적으로 평평합니다. 대부분의 동작은 framework hierarchy가 아니라
명시적 입력과 file-backed state를 가진 모듈입니다.

## 설치

Python 3.10 이상이 필요합니다.

```bash
git clone https://github.com/ashmoonori-afk/birkin.git
cd birkin
python -m pip install -e .
birkin setup
```

개발 환경:

```bash
python -m pip install -e ".[dev]"
pytest
```

## 첫 실행

```bash
# 대화형 설정
birkin setup

# 대화형 에이전트
birkin chat

# 모델과 네이티브 도구 확인
birkin models
birkin tools

# 로컬 gateway 또는 WebUI 시작
birkin gateway
birkin web
```

기본 provider는 Anthropic입니다. API key는 setup, 환경 변수,
`~/.birkin/config.json`으로 전달할 수 있습니다. 설치와 인증이 끝난 Claude 및
Codex CLI의 subscription-backed provider도 지원합니다.

## 네이티브 도구

Registry가 노출할 수 있는 기능:

- workspace 범위 file read, edit, write, listing
- 파괴적 command 승인이 있는 shell 실행
- HTTP fetch, web search, 시세 조회, citation 검증
- session 조회와 transcript 접근
- 투명한 memory operation
- 범위가 제한된 tool group을 쓰는 격리 subagent
- skill load, create, refine
- 로컬 또는 HTTP(S) PNG/JPEG/GIF/WebP용 `vision_analyze`
- opt-in Windows window listing과 screenshot

원격 이미지는 web fetch와 동일한 private/reserved address 및 redirect 검사를
거칩니다. `desktop_tools`가 정확히 `true`가 아니면 desktop tool은 registry에
등록되지 않습니다.

## 설정

설정은 `~/.birkin/config.json` 또는 `BIRKIN_HOME` 아래에 있습니다. 다음은
`birkin/config.py`의 실제 기본값을 사용한 대표 설정입니다.

```json
{
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "subagent_model": "claude-haiku-4-5-20251001",
  "api_key": null,
  "api_keys": [],
  "max_tokens": 4096,
  "temperature": 1.0,
  "max_turns": 24,
  "context_window": 200000,
  "auto_compact": true,
  "fallback_provider": "",
  "fallback_model": "",
  "fallback_cooldown": 300,
  "parallel_tools": true,
  "max_depth": 2,
  "shell_approval": "manual",
  "command_allowlist": [],
  "fs_jail": false,
  "checkpoints": true,
  "checkpoint_keep": 20,
  "redact_secrets": true,
  "spill_threshold": 30000,
  "disabled_tools": [],
  "desktop_tools": false,
  "self_improve": true,
  "a2a_enabled": false,
  "lsp_servers": {},
  "harness_enabled": true,
  "harness_turn_interval": 12,
  "harness_cooldown_min": 15,
  "harness_compact_review": true,
  "harness_max_edits": 12,
  "harness_prompt_budget": 20000,
  "harness_auto_approve": ["memory", "skill"],
  "web_port": 8787,
  "gateway_port": 8788,
  "budget_tokens_daily": 0,
  "budget_tokens_monthly": 0,
  "channels": {
    "http": {"enabled": true},
    "telegram": {
      "enabled": false,
      "token": "",
      "allowed_chat_ids": [],
      "stream": true
    }
  }
}
```

중요한 경계:

- `shell_approval: "manual"`은 파괴적 shell command 전에 묻습니다.
- `fs_jail: true`는 네이티브 file tool을 설정된 workspace root로 제한합니다.
- `redact_secrets: true`는 output 저장 전에 감지한 credential을 마스킹합니다.
- `disabled_tools`는 이름이 지정된 네이티브 tool을 registry에서 제거합니다.
- Gateway를 외부에 노출할 때는 HTTP 인증 또는 Telegram
  `allowed_chat_ids`를 함께 설정해야 합니다.
- 일/월 token budget은 `0`이면 비활성화됩니다.

대화형 설정에는 `birkin setup`, 유효한 tool set 확인과 toggle에는
`birkin tools`를 사용합니다.

## 메모리와 자기개선

birkin의 메모리는 일반 Markdown 파일 디렉터리입니다. note는 birkin 없이도
사용할 수 있고 Git으로 versioning할 수 있습니다.

개선 경로는 분리되어 있습니다.

1. 최근 작업을 검토합니다.
2. reviewer가 범위가 제한된 edit를 냅니다.
3. harness가 target, type, budget을 검증합니다.
4. 승인된 edit를 적용하고 ledger에 추가합니다.
5. entry를 확인하거나 rollback할 수 있습니다.

관련 명령:

```bash
birkin harness
birkin harness history
birkin morpheus
birkin nightly
birkin curate
birkin curate-memory
```

## 멀티에이전트와 프로토콜 표면

- **Subagent**는 새 대화, 제한된 tool, 선택적 skill을 받습니다. 부모 transcript를
  상속하거나 부모 memory에 쓰지 않습니다.
- **Moirai**는 Claude, Codex, API worker를 사용해 결정론적 workflow를 실행합니다.
- **Boulder/Odyssey**는 장기 goal step을 저장하고 검증합니다.
- **MCP**는 호환 client에 birkin tool을 노출합니다.
- **A2A**는 opt-in Agent2Agent v1.0 JSON-RPC endpoint와 agent card를 제공합니다.
- **Gateway**는 로컬 HTTP와 Telegram turn 사이에서 session을 warm 상태로 유지합니다.

## 검증

기본 test run은 offline입니다.

```bash
pytest
```

이 README를 작성한 시점에 suite는 2,300개 이상의 테스트와 82% 이상의 package
coverage를 통과합니다. Live-provider test는 기본적으로 제외되며
`BIRKIN_LIVE=1`이 필요합니다.

프로젝트에서 사용하는 static check:

```bash
python -m ruff check .
python -m bandit -r birkin
```

## 라이선스

birkin은 [MIT License](./LICENSE)로 배포됩니다.
