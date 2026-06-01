<div align="center">

```
 ██████╗ ██╗██████╗ ██╗  ██╗██╗███╗   ██╗
 ██╔══██╗██║██╔══██╗██║ ██╔╝██║████╗  ██║
 ██████╔╝██║██████╔╝█████╔╝ ██║██╔██╗ ██║
 ██╔══██╗██║██╔══██╗██╔═██╗ ██║██║╚██╗██║
 ██████╔╝██║██║  ██║██║  ██╗██║██║ ╚████║
 ╚═════╝ ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝
```

### 무료. 빠름. 밤마다 스스로 개선 — 검증은 당신이.

Claude 구독으로 **무료로 종일** 돌고, 따뜻한 영속 세션에서 **~3초**에 답하며,
모호한 일은 **명료해질 때까지 인터뷰**(Neurosis)하고, **모든 대화를 자동
저장**해 밤사이 기억으로 바꾸며(Morpheus), **회사 도구를 MCP로** 붙이고, **검증
권한은 당신에게** 남기는 — **의존성 0**의 파이썬 코어 CLI·텔레그램 에이전트.

🌐 **Language**: [English](./README.md) · 한국어

![python](https://img.shields.io/badge/python-3.10%2B-3776ab)
![runtime deps](https://img.shields.io/badge/runtime%20deps-0-2ea44f)
![tests](https://img.shields.io/badge/tests-432%20passing-2ea44f)
![skills](https://img.shields.io/badge/bundled%20skills-52-blue)
![platform](https://img.shields.io/badge/platform-macOS%20·%20Linux%20·%20Windows-lightgrey)

</div>

---

birkin은 Claude Pro/Max 구독으로 **API 키 없이, 토큰 과금 없이 종일 무료**로 돌릴
수 있는 개인·회사용 에이전트입니다. 터미널과 텔레그램에서 **하나의 메모리·스킬·
페르소나**로 대화하며, **놀라게 하지 않으면서 진짜로 도움이 되는 것**을 목표로
설계됐습니다.

- **무료 + 빠름.** 게이트웨이는 **Claude Code 자체**를 대화별 *따뜻한 영속*
  프로세스(stream-json)로 돌립니다. 콜드 스타트는 한 번만, 이후 응답은
  ~모델시간(**~3초**)이며 **유료 API 키가 아니라 Claude 구독**으로 청구됩니다.
  ([`docs/DECISIONS.md`](./docs/DECISIONS.md) ADR-026)
- **행동 전 명료화 (Neurosis).** 모호하거나 복잡한 요청엔 추측하지 않고,
  **수학적 모호도 게이팅**이 있는 **Socratic 딥 인터뷰**를 한 질문씩 진행해
  아이디어가 또렷해진 뒤 spec을 쓰고, **승인 후에만** 실행합니다.
- **자기개선 + 영수증 (Morpheus).** 모든 턴이 자동 저장되고, 밤마다 Morpheus가
  하루를 읽어 Obsidian 메모리를 갱신하고 스킬을 만들며 **위험한 동작은 아침
  검토용으로 큐잉**합니다.
- **회사용.** Claude Code의 **MCP** 서버(Notion·Drive·Gmail·사내 도구)를
  네이티브로 상속하고, 회사급 보안 하드닝을 갖췄습니다.

영감: [hermes-agent](https://github.com/NousResearch/hermes-agent),
[openclaw](https://github.com/openclaw/openclaw). 딥 인터뷰는
[gajae-code](https://github.com/Yeachan-Heo/gajae-code)에서 이식. 폭이 아니라
**신뢰 + 명료성의 깊이**에 집중합니다 —
[`docs/COMPARISON.md`](./docs/COMPARISON.md).

---

## 🎯 설계 의도

1. **기본이 무료.** 권장 백엔드는 `claude` CLI를 통한 **Claude 구독** — API 키도,
   유료 `extra_usage`도 없습니다. (직접-API OAuth는 *파킹*: third-party OAuth 앱
   사용은 유료로 과금됨 — ADR-026.)
2. **기본이 빠름.** 게이트웨이는 **대화별 따뜻한 `claude` 프로세스**를 유지해
   웜 응답이 매번 콜드 스타트가 아니라 모델시간입니다.
3. **stdlib 전용 런타임.** `dependencies = []`. 어디서나 설치 — 버전 드리프트
   없음. (pytest 등 개발 도구는 옵트인.)
4. **검색보다 컴파일.** 메모리는 `[[위키링크]]`·frontmatter·**polarity**·
   **version**(낙관적 잠금)·TTL을 가진 진짜 Obsidian 마크다운 vault — 불투명
   임베딩이 아닙니다. 손으로 편집 가능.
5. **승인 우선.** 메모리·스킬 쓰기는 자동(되돌릴 수 있는 로컬 파일), cron·shell은
   큐잉(위험도 정렬). 무인 Morpheus는 샌드박스(shell 없음).
6. **CLI 우선, 대시보드는 보조.** 진짜 터미널 라인 에디터(인라인 `/cmd` 드롭다운,
   단어 단위 편집, 멀티라인, 히스토리). 웹 UI는 *모니터링*.

---

## 🚀 설치

**macOS / Linux**
```bash
curl -fsSL https://raw.githubusercontent.com/ashmoonori-afk/birkin/main/scripts/install.sh | bash
```

**Windows (PowerShell)**
```powershell
irm https://raw.githubusercontent.com/ashmoonori-afk/birkin/main/scripts/install.ps1 | iex
```

**소스에서**
```bash
git clone https://github.com/ashmoonori-afk/birkin && cd birkin
uv run birkin            # 또는:  pip install -e .  &&  birkin
```

**Python 3.10+** 필요. 첫 실행 시 온보딩 마법사(방향키 탐색)가 뜹니다.

### 백엔드 선택

| 백엔드 | 방법 | 비용 |
|---|---|---|
| **Claude Code** (`claude`) — *권장* | `claude`에 로그인 후 `birkin model`에서 선택 | **무료** — Claude 구독, API 키 불필요 |
| **Anthropic API** | `export ANTHROPIC_API_KEY=sk-ant-…` | 유료(토큰당) |
| **OpenAI 호환** | provider `openai` + `base_url` (**Ollama** 가능) | 유료\* |
| **Codex** (`codex`) | `birkin model`에서 선택 | 자체 CLI 로그인 사용 |

\* Ollama는 아무 키나 허용. **게이트웨이**는 Claude(claude-cli) 경로를 웜·영속으로
돌려 빠릅니다.

---

## 🗺️ 아키텍처

```
        터미널 (REPL)                           Telegram / HTTP
              │                                       │
              ▼                                       ▼
   ┌────────────────────────┐          ┌──────────────────────────────────┐
   │ repl.py + inline_      │          │ gateway/core.py                  │
   │ complete.py            │          │  · /help /new /restart /hard_    │
   │  · /cmd 드롭다운        │          │    restart /models /neurosis     │
   │  · 단어 단위 편집       │          │  · 대화별 WARM claude            │
   │  · 멀티라인 · 히스토리  │          │    (claude_session.py, stream-   │
   └───────────┬────────────┘          │    json) — 무료 + ~3초           │
               │                       └───────────────┬──────────────────┘
               │   하나의 메모리 · 스킬 · 페르소나 공유   │
               └───────────────┬───────────────────────┘
                               ▼
        ┌──────────────────────────────────────────────────────────────┐
        │   에이전트 (Claude Code, 또는 API 키 시 birkin 자체 루프)     │
        │   도구: files · shell · web · subagent · memory_* · skills    │
        │   + Claude Code의 MCP 서버 상속 (회사 도구)                  │
        │   + birkin-as-MCP-server (mcp_server.py): 메모리/스킬/propose │
        │     도구 — 무료 claude 경로에서도 구조 유지                  │
        └───────────────┬───────────────────────────────┬──────────────┘
                         ▼                               ▼
              ~/.birkin/vault/*.md                ~/.birkin/sessions/
              (Obsidian 메모리:                   auto__*.json
               polarity · version · TTL)          (매 턴 자동 저장)
                         ▲                               │
                         │                               ▼
        ┌────────────────┴───────────────────────────────────────────┐
        │  Morpheus (morpheus.py) — 야간 04:00, 무료 + 샌드박스       │
        │   최근 24h 자동저장 턴 읽기 ─▶ 메모리/스킬 작성(birkin MCP)  │
        │   ─▶ cron/shell 제안 (승인 게이트)                          │
        └──────────────────────────┬──────────────────────────────────┘
                                   ▼
                    approvals.py + risk.py  ─▶  `birkin review`
        (메모리/스킬=자동 · cron/shell=큐잉; shell-cron은 shell 게이트
         우회 불가)

   Neurosis(딥 인터뷰): 모호한 요청 ─▶ 모호도 게이팅 Socratic Q&A
   ─▶ spec(~/.birkin/specs/) ─▶ 승인 후에만 실행
```

---

## 🤔 그냥 Claude.ai / API를 쓰지 않는 이유

birkin은 Claude를 대체하지 않습니다 — `claude` CLI를 **감싸서** 지속성·구조·야간
학습을 더합니다. 일회성 대화면 Claude.ai로 충분하고, 수요일쯤 내 맥락을 아는
에이전트가 필요하면 birkin이 그 래퍼입니다.

| | Claude.ai / API | birkin |
|---|---|---|
| 비용 | 구독 또는 토큰당 API | **구독만 — API 과금 없음** |
| 메모리 | 세션 한정 | 세션 넘어 지속·검색 가능한 Obsidian vault |
| 텔레그램 | — | 터미널과 같은 세션·메모리·페르소나 |
| 모호함 | 추측하고 진행 | **Neurosis**가 명료해질 때까지 묻고 spec 작성 |
| 자기개선 | — | **Morpheus**가 밤마다 메모리/스킬 갱신 |
| 감사 추적 | — | 모든 턴 기록, `birkin trace <id>` 재생 |
| 내 파일 / MCP | 수동 붙여넣기 | 네이티브: Notion·Drive·Gmail·사내 서버 |
| 보안 모델 | Anthropic이 관리 | 게이트·redaction·승인 큐를 내가 통제 |

---

## 🎮 빠른 시작

### 무료 + 빠르게 (게이트웨이)

```bash
$ birkin model          # "claude"(Claude Code) 선택 — 무료, API 키 불필요
$ birkin gateway        # 웜 영속 서비스: HTTP + (선택) Telegram, 웜 응답 ~3초
```

채팅(터미널/텔레그램)에서 `/`를 누르면 명령 메뉴가 뜹니다. 게이트웨이 명령:

| 명령 | 동작 |
|---|---|
| `/new` (`/reset`) | 새 대화 |
| `/restart` (`/restart-gateway`) | **소프트 재시작** — config/persona/memory 재로딩, 프로세스 유지 |
| `/hard_restart` | **하드 재시작** — 게이트웨이 re-exec(코드 변경 반영), 재시작 루프 방지 |
| `/models [이름]` | 모델 목록/**선택** — 적용 위해 자동 하드재시작 |
| `/neurosis [--quick\|--standard\|--deep] <아이디어>` | **딥 인터뷰** 시작/재개 |

### 명료해질 때까지 인터뷰 (Neurosis)

모호·복잡한 요청이면 birkin이 먼저 *"진행 전에 모호한 부분과 핵심 결정사항을
다시 한번 확인하겠습니다"* 라고 한 뒤 한 질문씩 물어 모호도를 낮추고, spec을 쓴
다음 **승인 후에만** 실행합니다.

```bash
you > /neurosis 회사 인스타 캠페인 새로 기획해줘
birkin > Round 0 | 구성요소 확인 …
```

`birkin neurosis "<아이디어>"`로 CLI에서 시드. 자동 트리거 기본 on(`neurosis_auto`).

### 자동으로 기억하는 대화

모든 턴이 `~/.birkin/sessions/`에 자동 저장되고 밤사이 Morpheus가 기억으로
바꿉니다. 즉석에서 사실을 남길 수도 있습니다:

```bash
you > /remember 나는 군더더기 없는 간결한 답을 선호해
birkin > Noted as [[Profile - reply-style]].
```

### Morpheus — 밤에 자기개선, 아침에 검토

```bash
$ birkin daemon --install   # OS 작업 등록 (cron / launchd / schtasks)
$ birkin morpheus --dry-run # 오늘 밤 실행 미리보기 (과금 없음)
$ birkin review             # 다음 날 아침 하나씩 승인/거부
$ birkin trace <run-id>     # 과거 턴 감사 재생
```

Morpheus는 **무료**(샌드박스 Claude + birkin MCP 도구), **shell 없이** 돌고,
메모리/스킬은 자동, cron/shell은 큐잉됩니다.

### 회사 도구 연결 (MCP)

```bash
$ birkin mcp                # 게이트웨이가 상속하는 MCP 서버 목록 (Notion 등)
$ birkin mcp add <이름> …   # `claude mcp`로 패스스루
```

게이트웨이는 Claude Code의 MCP 서버를 네이티브로 상속합니다. `gateway_allowed_tools`로
무인 게이트웨이가 특정 회사 도구를 프롬프트 없이 쓰게 할 수 있습니다.

---

## 📟 명령 요약

```bash
birkin                              # 채팅 시작 (첫 실행 → 온보딩)
birkin gateway                      # 무료·웜 서비스 (HTTP + Telegram)
birkin neurosis "<아이디어>"        # 딥 인터뷰 시드 (/neurosis로 진행)
birkin model                        # 모델 선택 (Claude Code = 무료)
birkin mcp [list|add|remove|…]      # MCP 서버 관리 (회사 도구)
birkin morpheus [--dry-run]         # 야간 자기개선 즉시 실행
birkin daemon  [--install]          # Morpheus + cron 스케줄러
birkin review                       # 제안 동작 승인/거부
birkin runs / trace <id> / budget   # 감사 로그 · 재생 · 토큰 예산
birkin skills [validate|sync]       # 스킬 목록 / 린트 / 미러
birkin permission [--access …]      # 자동 승인 · CLI 접근 수준
birkin web                          # 모니터링 대시보드
```

### REPL 슬래시 명령

`/help`로 전체 목록. 라인 에디터: **Ctrl+←/→** 단어 이동, **Ctrl-W** 단어 삭제,
**Ctrl-U/Ctrl-K** 현재 줄의 시작/끝까지 삭제, **↑/↓** 히스토리, **Shift+Enter**
줄바꿈, 인라인 `/` 드롭다운.

| 그룹 | 명령 |
|---|---|
| **대화** | `/new` · `/retry` · `/undo` · `/compact` · `/clear` |
| **명료화** | `/neurosis [name]` (딥 인터뷰) |
| **모델** | `/model` · `/models [name]` · `/provider` · `/temp` |
| **스킬** | `/skills` · `/skill <name>` · `/reload` · `/learn` |
| **메모리** | `/memory <query>` · `/remember <text>` · `/vault` · `/soul` · `/personality` |
| **도구** | `/mcp` · `/tools` |
| **자율** | `/morpheus` · `/review` · `/cron` · `/permission` |
| **세션** | `/save` · `/load` · `/sessions` |
| **시스템** | `/system` · `/config` · `/update` · `/help` · `/quit` |

---

## 🧠 메모리 & 🗣️ 페르소나

**메모리**는 `~/.birkin/vault` — `type`·`polarity`(positive/known-failure)·
`version`(낙관적 잠금)·TTL·`[[위키링크]]`를 가진 출처 있는 마크다운 노트. 도구:
`memory_search`·`memory_get_note`·`memory_write_note`·`memory_link`.
`evidence_required: true`로 출처 없는 노트 거부.

**페르소나**는 `~/.birkin/SOUL.md` — 모든 표면에 주입되는 따뜻하고 편집 가능한
말투(REPL은 매 턴, 게이트웨이는 세션 시작 시). `/personality warm|concise|mentor|
direct`로 프리셋 교체, `/soul`로 보기/편집.

---

## 🧩 스킬

스킬은 `SKILL.md`(frontmatter + 마크다운)를 가진 디렉토리로 agentskills.io /
hermes 표준과 호환. [`skills/`](./skills) 아래 **52개 번들**(research·software·
writing·data·devops·marketing·planning/**neurosis**·automation/**morpheus**·
**odyssey**·creative/**codex-image-gen** 등) + `~/.birkin/skills/`의
내 스킬(번들을 이름으로 가림). `load_skill`로 필요 시 전체 로드, `create_skill`/
`improve_skill`은 승인 게이트 경유, `birkin skills validate`로 린트 +
`py_compile`, 편집 시 **핫리로드**.

---

## 🔒 보안 (회사급)

무인으로도 놀라게 하지 않도록 설계 — [`docs/DECISIONS.md`](./docs/DECISIONS.md)
ADR-029·ADR-032:

- **cron→shell 게이트.** 자동 승인된 `cron`이 `shell` 페이로드를 우회시킬 수
  없음 — `shell`도 승인돼 있지 않으면 검토용으로 큐잉.
- **게이트웨이는 절대 `--dangerously-skip-permissions` 아님.** 도달 가능한 채팅이
  전권 프로세스에 닿을 수 없게 `cli_access:full`을 `workspace`로 강제.
- **Windows `cmd /c` 주입 차단.** CLI 인자에 셸 메타문자(`& | < > ^`)가 있으면
  거부 — 신뢰된 운영자 입력(`birkin mcp add …`)이라도 명령 체이닝을 막음.
- **Telegram 접근 제어 + 신뢰 게이트 메모리.** `allowed_chat_ids`로 봇 사용자
  제한; *열린* 봇의 낯선 메시지는 자동 저장·기억 **안 함**(메모리 오염 방지).
- **시크릿 redaction.** 트랜스크립트는 디스크/메모리에 닿기 전 마스킹
  (Anthropic/OpenAI/Google/GitHub/Slack/AWS 키·토큰·Bearer·PEM).
- **At rest.** 상태·트랜스크립트는 원자적·`0o600`. 평문 config 토큰보다
  `TELEGRAM_BOT_TOKEN` 환경변수 권장.

---

## ⚙️ 설정

모든 상태는 `~/.birkin` 아래 (`BIRKIN_HOME`로 변경):

```
~/.birkin/
├── config.json     # provider, model, gateway, autosave, neurosis, 권한…
├── vault/          # Obsidian 시맨틱 메모리
├── skills/         # 사용자·에이전트 작성 스킬
├── sessions/       # 자동 저장 트랜스크립트(auto__*.json) — Morpheus 입력
├── specs/          # Neurosis 딥 인터뷰 spec
├── neurosis/       # 인터뷰 상태(재개 가능)
├── runs/           # 턴별·Morpheus 실행 요약
├── ledger.jsonl    # append-only 감사 로그
├── pending/        # 승인 대기 동작
└── status.json     # 데몬 하트비트
```

자주 만지는 키:

```json
{
  "provider": "claude-cli",
  "model": "opus",
  "gateway_model": "sonnet",
  "gateway_persistent": true,
  "gateway_allowed_tools": [],
  "autosave_transcripts": true,
  "neurosis_auto": true,
  "neurosis_threshold": null,
  "morpheus_hour": 4,
  "auto_approve": ["memory", "skill"],
  "channels": {
    "http": {"enabled": true},
    "telegram": {"enabled": false, "token": "", "allowed_chat_ids": []}
  }
}
```

API 키는 환경변수 우선; Claude Code 백엔드는 불필요. config.json의 키는
`chmod 600`으로 저장.

---

## 🛠️ 현재 위치

- 오프라인 **테스트 432개** 통과(API 키 없이), **번들 스킬 52개**, **런타임
  의존성 0**, Python 3.10+.
- 무료·빠른 게이트웨이(웜 영속 Claude, ~3초), Neurosis 딥 인터뷰, 자동저장 →
  기억, 회사 MCP, 회사급 보안 하드닝.
- 결정 근거: [`docs/DECISIONS.md`](./docs/DECISIONS.md)(ADR 001–033). 라이브
  상태: [`docs/STATUS.md`](./docs/STATUS.md). 비교:
  [`docs/COMPARISON.md`](./docs/COMPARISON.md).
- **계획(v2):** [`docs/v2.md`](./docs/v2.md) — Model Router·Hashline 편집·
  IntentGate·Prompt-Gate·**Osiris** 검증자·**Boulder** 상태, 그리고 on-demand
  **Odyssey** 목표-완수 사이클(oh-my-openagent에서 차용).

---

## 🙌 기여

스킬은 **MIT 라이선스**라 가장 쉽게 기여할 수 있는 지점입니다: 스킬은
`SKILL.md`(frontmatter + 마크다운)를 가진 디렉터리일 뿐 — 형식은
[`skills/`](./skills) 아래 아무 폴더나 참고하고, `birkin skills validate`로 린트한
뒤 새 스킬/개선 PR을 올려주세요. 버그·기능 제안은 이슈로 환영합니다.

birkin이 돈이나 시간을 아껴줬다면 **레포에 별(star)** 을 눌러주는 게 가장 큰
도움입니다 — 다른 Claude 구독자들이 birkin을 찾는 데 도움이 됩니다. ⭐

---

## 📄 라이선스

이중: **birkin 파이썬 패키지**(`birkin/`)는 **Proprietary — All Rights
Reserved**(© 2026 ashmoonori). 검토용으로 소스 공개, 서면 허가 없이 사용·복사·
수정·배포·상업적 권리 없음. **번들 스킬 카탈로그**(`skills/`)는 **MIT** —
NousResearch/hermes-agent·openclaw 카탈로그를 본떴고 일부 이식; 딥 인터뷰 스킬은
Yeachan-Heo/gajae-code에서 각색. 업스트림 MIT 조건·출처 표기 유지.
[`LICENSE`](./LICENSE), [`NOTICE`](./NOTICE) 참조.
