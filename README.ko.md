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
- 명시적 승인 뒤에만 실행되는 제한된 워커 continuation
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

birkin이 `codex app-server` 자식을 시작할 때는 plugin과 MCP server는 유지하되
해당 자식의 Codex plugin hook을 비활성화합니다. 따라서 전역
`UserPromptSubmit` hook이 birkin 내부 `<system-context>`를 사용자 입력으로
오인하지 않습니다.

### 능동 음성 제어

음성 기능은 birkin과 함께 설치됩니다. OpenAI STT/TTS에는 Platform API
키가 필요합니다.

```bash
export OPENAI_API_KEY="..."
uv run birkin gateway
```

다른 터미널에서 기본 마이크를 계속 사용하는 음성 모드를 시작합니다.

```bash
uv run birkin voice start \
  --gateway-url http://127.0.0.1:8788/message
uv run birkin voice status
```

`start`는 인증된 worker 준비 완료를 기다리고 중복 daemon을 거부하며,
인증된 제어 상태와 로그를 `~/.birkin/voice` 아래에 기록합니다. 상태
디렉터리는 현재 OS 계정으로 제한되므로, 사용자 지정 `BIRKIN_HOME`은
사용자 ACL을 지원하는 파일 시스템에 두십시오. 실행 중인 daemon PID가
일시적으로 응답하지 않으면 `start`는 상태를 삭제하고 고아 중복 daemon을
실행하는 대신 `UNREACHABLE`을 보고합니다. `status`는 현재 PID를 보여
주며 `RUNNING`일 때만 종료 코드 `0`을 반환합니다. `STOPPING`,
`UNREACHABLE`, `INACTIVE`는 종료 코드 `1`을 반환합니다. 현재의 제한된
음성 턴이 끝난 뒤 daemon을
종료하려면 다음을 실행합니다.

```bash
uv run birkin voice stop
```

해당 턴이 제어 대기 시간보다 오래 걸리면 `stop`은 `STOPPING`을 출력하고
종료 코드 `1`을 반환하지만, 수락된 종료는 계속 진행됩니다. `voice
status`로 상태를 확인하십시오.

녹음 파일과 결정적 입력은 계속 one-shot 모드에서만 사용합니다.

```bash
uv run birkin voice --once \
  --audio wake.wav \
  --command-audio command.wav \
  --gateway-url http://127.0.0.1:8788/message \
  --tts-output reply.pcm \
  --no-playback
```

one-shot에서 `--audio`와 `--command-audio`를 생략하면 기본 마이크에서
깨우기/명령 구간을 제한 시간만큼 수집합니다. `--background`를 추가하면
`~/.birkin/voice/jobs` 아래 영속 작업 영수증을 받습니다. CI나 문제 분석에는
`--transcript "Daddy is home" --command "status"`로 결정적 입력을 줄 수
있습니다. Daemon `start`는 live microphone 옵션만 받습니다. 파일,
transcript, command, background, `--once` 입력은 worker를 실행하기 전에
실패합니다.

중첩된 `voice` 설정 블록은 대응하는 CLI 플래그의 기본값이며, 명시한
플래그가 우선합니다. 빈 `gateway_url`은 깨우기 fixture 실행을 오프라인으로
유지합니다. Gateway 전달에는 값을 설정하거나
`http://127.0.0.1:8788/message` 같은 정확한 loopback HTTP `/message`
주소를 `--gateway-url`로 넘깁니다. loopback이 아닌 host, HTTPS, 자격증명,
query, fragment는 거부됩니다. 로컬 HTTP 채널에 공유 비밀을 설정했다면
`BIRKIN_HTTP_TOKEN`을 지정하십시오. 음성 client는 검증된 loopback
endpoint에만 이 token을 전달합니다.

깨우기 문구는 명령 경로를 여는 신호일 뿐 인증이 아닙니다. 음성 요청도
`Gateway.handle("voice", ...)`를 통과하며 Telegram의 승인 작업 표식을
얻지 못합니다. 제한된 STT는 `gpt-transcribe`, 응답 음성은
`gpt-4o-mini-tts`를 사용하며 생성 음성은 AI 음성입니다. Codex/ChatGPT
로그인은 Audio API용 `OPENAI_API_KEY`를 대신하지 않습니다.


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
  "cli_network_access": false,
  "egress": {
    "enabled": true,
    "enforced": true,
    "max_bytes": 1048576,
    "destinations": {
      "trusted-api": {
        "url": "https://api.example.com/submissions",
        "method": "POST",
        "automatic": true,
        "content_types": ["application/json"],
        "max_bytes": 1048576,
        "auth_env": "EXAMPLE_SUBMIT_TOKEN"
      }
    }
  },
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
  "voice": {
    "wake_phrase": "Daddy is home",
    "gateway_url": "",
    "session_id": "voice-local",
    "sample_rate": 24000,
    "stt_model": "gpt-transcribe",
    "tts_model": "gpt-4o-mini-tts",
    "tts_voice": "coral",
    "tts_instructions": "Speak concisely and clearly.",
    "background_workers": 2
  },

  "channels": {
    "http": {"enabled": true},
    "telegram": {
      "enabled": false,
      "token": "",
      "allowed_chat_ids": [],
      "stream": true
    },
    "slack": {"enabled": false, "webhook_url": ""},
    "discord": {"enabled": false, "webhook_url": ""}
  }
}
```

중요한 경계:

- `shell_approval: "manual"`은 파괴적 shell command 전에 묻습니다.
- Windows shell 작업은 `cmd.exe`로 실행되고 검증된 쓰기 가능한
  `TEMP`/`TMP`를 받으므로 장시간 실행되는 gateway, scheduler, daemon에서도
  Bun·npm 같은 도구가 정상 동작합니다. PowerShell은 명시적으로 요청할 때만
  사용합니다.
- `fs_jail: true`는 네이티브 file tool을 설정된 workspace root로 제한합니다.
- `redact_secrets: true`는 output 저장 전에 감지한 credential을 마스킹합니다.
- `disabled_tools`는 이름이 지정된 네이티브 tool을 registry에서 제거합니다.
- Gateway를 외부에 노출할 때는 HTTP 인증 또는 Telegram
  `allowed_chat_ids`를 함께 설정해야 합니다.
- Slack과 Discord는 송신 전용 adapter입니다. HTTPS incoming-webhook URL이
  필요하며 message를 각각 3,500자와 2,000자로 제한합니다.
- 일/월 token budget은 `0`이면 비활성화됩니다.

대화형 설정에는 `birkin setup`, 유효한 tool set 확인과 toggle에는
`birkin tools`를 사용합니다.

`submit_payload`가 기본 outbound-write 경로입니다. inline JSON 또는 text를
받아 `egress.destinations`의 정확한 destination 이름만 해석하고, 최종 bytes를
canonicalize한 뒤 DNS/socket보다 먼저 검사합니다. 인증은 `auth_env`에서
destination별로 주입하고, 한 번만 전송하며, body나 credential이 없는
intent/outcome metadata를 `~/.birkin/egress-receipts.jsonl`에 기록합니다.
자동 전송은 `automatic: true`인 profile만 허용하고, 알 수 없거나
non-automatic인 destination은 차단합니다. Profile은 HTTPS/443, 고정된
method/path/content-type/byte cap만 허용하며 query, fragment, userinfo, proxy,
redirect를 허용하지 않습니다. 일반 `redact_secrets` 설정으로 이 pre-send
검사를 끌 수 없습니다.

기본 `egress.enforced: true`에서는 broker를 우회할 수 있는 native
`run_shell`과 `spawn_subagent` capability를 노출하지 않습니다. Model이 제어하는
`web_fetch` URL과 `web_search` query에도 network 전에 같은 secret scan을
적용하며, 일반 public research는 계속 사용할 수 있습니다. `enforced`를
`false`로 바꾸면 raw native capability가 복원되고 security warning이 표시됩니다.

`cli_network_access`의 기본값은 `false`입니다. 이를 켜면 Codex child가 raw
network를 사용해 inspected-egress destination/payload 검사를 우회하므로 Birkin이
security warning을 냅니다. Workspace 파일시스템 격리와
`approval_policy="never"`는 유지되지만 raw network는 명시적 escape hatch이며
기본 submission 경로가 아닙니다. `cli_access: "full"`은 별도의 위험한
host-access opt-in이며, 외부에서 접근 가능한 gateway에는 절대 상속되지 않습니다.

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

## Integration workflow

지속되는 subagent run은 `/dash`와 REPL에서 확인할 수 있습니다.

```text
/agents
/attach <run-id>
/send <run-id> <message>
```

`/goal set <objective> [--budget N] [--gate "command"]`로 active goal 하나를
저장합니다. `/goal show`, `/goal pause`, `/goal done`으로 상태를 관리합니다.
gate command는 goal store에서 직접 실행하지 않으며, goal을 완료할 때 기존 shell
approval queue를 거칩니다.

`/sessions <query>`는 저장된 transcript를 검색하고 date, channel, model,
snippet, score metadata를 반환합니다. `--since 30d`, `--from telegram`
(`--channel`도 지원), `--model <name>` filter는 AND로 결합됩니다. 인자 없는
`/sessions`는 기존 saved-session 목록을 그대로 표시합니다.

Cron job은 `"type": "monitor"`와 `monitor_url` 또는 `monitor_script` 중 정확히
하나를 사용할 수 있습니다. 제한된 결과가 바뀔 때만 알림을 보내며 URL monitor는
web SSRF guard, 30초 timeout, 최대 256 KiB response 제한을 적용합니다. Fetch
실패는 변경으로 취급하지 않습니다.

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
