<div align="center">

```
 ██████╗ ██╗██████╗ ██╗  ██╗██╗███╗   ██╗
 ██╔══██╗██║██╔══██╗██║ ██╔╝██║████╗  ██║
 ██████╔╝██║██████╔╝█████╔╝ ██║██╔██╗ ██║
 ██╔══██╗██║██╔══██╗██╔═██╗ ██║██║╚██╗██║
 ██████╔╝██║██║  ██║██║  ██╗██║██║ ╚████║
 ╚═════╝ ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝
```

### 밤사이 스스로 성장하고, 아침에 너에게 영수증을 준다.

**Self-improving by night. Audited by you.**

가벼운 CLI 에이전트 워크스페이스. **자고 있는 동안 스스로 개선하고, 무엇을
했는지 영수증을 남긴다**: 승인 게이트가 걸린 야간 루틴 (**Morpheus**),
매 turn마다 기록되는 run record + append-only 감사 ledger, polarity까지
다루는 Obsidian 메모리, 위험 등급으로 정렬되는 승인 인박스, `skills validate`
무결성 게이트 — 전부 **의존성 0개**의 Python 코어 안에서.

🌐 **Language**: [English](./README.md) · 한국어

![python](https://img.shields.io/badge/python-3.10%2B-3776ab)
![runtime deps](https://img.shields.io/badge/runtime%20deps-0-2ea44f)
![tests](https://img.shields.io/badge/tests-277%20passing-2ea44f)
![coverage](https://img.shields.io/badge/coverage-76%25-2ea44f)
![platform](https://img.shields.io/badge/platform-macOS%20·%20Linux%20·%20Windows-lightgrey)
![license](https://img.shields.io/badge/package-Proprietary-orange)
![license](https://img.shields.io/badge/bundled%20skills-MIT-green)

</div>

---

대부분의 자기개선 에이전트는 두 가지 함정에 빠진다 — **결정에서 사용자를
배제하거나**, **흔적을 남기지 않거나**. birkin은 둘 다 안 한다. 자고 있는
사이에 **Morpheus**가 하루를 읽고, Obsidian 메모리를 갱신하고, 새 스킬 초안을
쓰고, **결과가 영향 큰 행동(cron, shell)은 전부 아침 승인 큐로** 보낸다. 모든
turn은 run record + ledger 한 줄로 남으므로 과거 결정을 그대로 재생할 수 있다
— `birkin trace <run-id>`. 메모리 노트는 **polarity**(긍정 / 알려진 실패),
**version**(낙관적 락), 선택적 evidence 요구를 가지며, 번들 스킬은 요청 시
프론트매터 린트 + `py_compile`까지 거친다.

가진 것 위에서 동작한다 — **API key** (Anthropic / OpenAI 호환 / Ollama) 또는
이미 로그인한 로컬 에이전트 CLI (**Claude Code** / **Codex**).

[hermes-agent](https://github.com/NousResearch/hermes-agent)와
[openclaw](https://github.com/openclaw/openclaw)에서 영감을 받았다.
의도적으로 **너비**(채널·프로바이더·스킬 수)에 베팅하지 않고 **신뢰의 깊이**에
베팅 — 출처 기반 비교는 [`docs/COMPARISON.md`](./docs/COMPARISON.md) 참조.

---

## 🎯 설계 의도

birkin은 영감을 준 두 프로젝트보다 의도적으로 **더 작고 더 조심스럽다**. 다른
모든 결정은 이 다섯 가지에서 파생된다:

1. **Stdlib만 사용하는 런타임.** `pyproject.toml`의 `dependencies = []`.
   어떤 노트북·서버·갓 설치한 OS에도 설치 가능 — 버전 드리프트도, 핀
   관리 지옥도 없음. (`pytest` 같은 개발 도구는 선택 사항.)
2. **검색이 아니라 컴파일.** 메모리는 진짜 Obsidian 마크다운 노트 vault —
   `[[wikilink]]`, frontmatter, **polarity**(긍정 vs 알려진 실패),
   **version**(낙관적 락), TTL — 불투명한 임베딩 저장소가 아님. Obsidian에서
   열어서 직접 편집 가능.
3. **승인 우선.** 메모리·스킬 쓰기는 자동 적용 (로컬 파일 변경이라 되돌리기
   쉬움); cron 스케줄과 shell 명령은 큐잉. 위험 등급으로 가장 위험한
   제안부터 화면 위에.
4. **CLI 우선, 대시보드는 보조.** 채팅은 터미널 안에서 진짜 라인 에디터로
   (인라인 `/명령` 드롭다운, Shift/Ctrl/Alt+Enter 줄바꿈, 영속 히스토리).
   웹 UI는 *모니터링* 용 — 작업, run, 승인 현황만.
5. **범위에 정직하게.** hermes는 실행 백엔드 더 많고 openclaw는 채널 더
   많으며 5,400개 스킬 레지스트리도 있다. birkin이 거는 판은 **신뢰의 깊이**:
   `skills validate` + `py_compile`, 위험 등급 승인, polarity 메모리,
   토큰 예산 거버너, ledger 기반 감사 trail. 출처 기반 비교는
   [`docs/COMPARISON.md`](./docs/COMPARISON.md) 참조.

---

## 🗺️ 아키텍처

```
                              ┌───────────────────────────┐
                              │            you            │
                              └──┬──────────────────────┬─┘
                                 │ terminal             │ browser
                                 ▼                      ▼
              ┌──────────────────────────────┐   ┌────────────────────┐
              │      REPL  (repl.py)         │   │  web/server.py     │
              │  ┌────────────────────────┐  │   │  monitoring only   │
              │  │ inline_complete.py     │  │   │  ─ /api/status     │
              │  │  ─ /cmd 드롭다운       │  │   │  ─ /api/runs       │
              │  │  ─ Shift/Ctrl/Alt+Ent  │  │   │  ─ /api/approvals  │
              │  │  ─ 멀티라인 + paste    │  │   │  ─ /api/skills     │
              │  │  ─ ↑/↓ 히스토리        │  │   └─────────┬──────────┘
              │  └────────────────────────┘  │             │
              └──────────────┬───────────────┘             │
                             │                             │
              ┌──────────────┴─────────────────────────────┴──┐
              │       gateway / 채널 (gateway/*)              │ ◀── Telegram
              │           하나의 공유 Session                 │
              └──────────────┬───────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │                       Session   (runtime.py)                     │
  │                                                                  │
  │     ┌────────────────────────────────────────────────────┐       │
  │     │        agent.py   ⟲ tool-calling 루프              │       │
  │     │        (provider 무관, Anthropic은 streaming)      │       │
  │     └──┬─────────────────────┬─────────────────────────┬─┘       │
  │        ▼                     ▼                         ▼         │
  │   ┌─────────┐         ┌──────────────┐         ┌─────────────┐   │
  │   │  llm.py │         │   tools/     │         │  skills/    │   │
  │   │         │         │              │         │             │   │
  │   │ Anthropic│        │ files        │         │ SKILL.md    │   │
  │   │ OpenAI   │        │ shell        │         │ loader      │   │
  │   │ claude-cli        │ web          │         │ manager     │   │
  │   │ codex-cli│        │ subagent ──┐ │         │ validate.py │   │
  │   │ local-cli│        │ memory_*  ─┼─┼────────▶│  py_compile │   │
  │   └─────────┘         └────────────┼─┘         │  sync       │   │
  │                                    │           └─────┬───────┘   │
  │                                    ▼                 ▼           │
  │                              subagent.py        memory.py        │
  │                              (격리됨)          (Obsidian vault)  │
  └──────────────────────────────────────────────────────────────────┘
                             │                       │
                             │                       ▼
                             │              ~/.birkin/vault/*.md
                             │              ─ polarity (+/−)
                             │              ─ version (낙관적 락)
                             │              ─ TTL (expires_at)
                             ▼
        ┌────────────────────────────────────────────────────┐
        │  자율 (scheduler.py · cron.py · morpheus.py)       │
        │                                                    │
        │   04:00 ─▶ 자기개선 ─▶ 최근 24h 분석              │
        │            ├─ 메모리 / 스킬 갱신     (자동)        │
        │            └─ cron / shell 제안 ───┐               │
        └────────────────────────────────────┼───────────────┘
                                             │
                                             ▼
                              ┌─────────────────────────────────┐
                              │  approvals.py + risk.py         │
                              │  ─ memory/skill = 낮음 (자동)   │
                              │  ─ cron        = 중간 (큐잉)    │
                              │  ─ shell       = 높음 (큐잉)    │
                              └──────────┬──────────────────────┘
                                         │
                                         ▼
                            `birkin review`  /  /api/approvals

        매 turn:  run record (estTokens, 사용 도구, iteration)
                  ──▶  ~/.birkin/runs/  +  ~/.birkin/ledger.jsonl
                  (감사 replay: `birkin trace <run-id>`,
                   예산 거버너: budget.py)
```

**다이어그램 읽는 법.** 실선 화살표는 한 turn의 제어/데이터 흐름. 점선
영역(자율, 감사)은 동기 루프 *아래에* 깔려 있다 — 사용자 입력이 아니라
daemon과 ledger가 굴린다.

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

**Python 3.10+** 필요. 첫 실행은 온보딩 위저드 — **↑/↓ 와 Enter**로 이동
(키/경로 입력 외엔 타자 칠 일 없음).

### 백엔드 선택

birkin은 아래 중 *하나*가 필요 — 위저드(또는 `birkin model`)가 설정해준다:

| 백엔드 | 방법 | API key |
|---|---|---|
| **Anthropic** | `export ANTHROPIC_API_KEY=sk-ant-…` | 필요 |
| **OpenAI 호환** | provider `openai` + `base_url` (**Ollama**도 OK) | 필요\* |
| **Claude Code** (`claude`) | `birkin model`에서 선택 | 불필요 — CLI 자체 로그인 사용 |
| **Codex** (`codex`) | `birkin model`에서 선택 | 불필요 — CLI 자체 로그인 사용 |
| **임의 로컬 CLI** (`local-cli`) | config의 `cli_command` (argv) 설정 | 불필요 — argv 실행, stdin으로 프롬프트 전달 |

\* Ollama는 아무 키나 받음. PowerShell: `$env:ANTHROPIC_API_KEY="sk-ant-…"`.

### API key 없어요? Claude Code / Codex를 쓰세요

`claude` 또는 `codex`가 `PATH`에 있으면 `birkin model`이 **Local CLI agents**
섹션에 표시한다. birkin은 자신의 정체성 + 메모리 + 메시지와 가장 관련 있는
스킬들을 CLI 프롬프트에 주입해서, 그 에이전트가 *birkin으로서* 답하고,
너를 기억하고, 너의 스킬을 따르게 만든다.

CLI 에이전트는 기본적으로 **쓰기 가능** (워크스페이스 안 샌드박스). 승인/샌드박스를
완전히 우회하려면: `birkin permission --access full`. **신뢰하는 워크스페이스에서만**
사용.

---

## 🎮 빠른 시작 — 5가지 워크플로우

> 아래 예시는 전부 실제 동작. 복사·붙여넣기·실행.

### 1. 너를 기억하는 채팅

```bash
$ birkin
you > /remember 짧고 간결하게 답해. 서론 없이.
birkin > [[Profile - reply-style]] 노트로 저장됨.
you > /memory preference
birkin > Vault에 preference 노트 3개:
         - [[Profile - reply-style]] …
         - [[Profile - timezone]] …
```

### 2. 5000자짜리 PRD를 한 번에 paste

REPL 안에서 **Shift+Enter** (Kitty Keyboard Protocol 미지원 터미널이면
Ctrl-J / Alt+Enter)로 줄바꿈 삽입. **Enter**가 제출. 인라인 `/` 드롭다운이
타이핑에 따라 슬래시 명령을 필터링; ←/→, Home/End, Delete, ↑/↓ 히스토리도
다 동작. 긴 줄은 가로 스크롤로 처리해서 터미널 레이아웃이 깨지지 않는다.

```
you > /help⏎          (모든 슬래시 명령 그룹별 표시)
you > 아래 brief 기반으로 GTM 플랜 짜줘.⇧⏎
      ⇧⏎
      [5000자+ 본문 N줄 paste]⏎
birkin > [답변 스트리밍]
```

### 3. 성공한 turn 하나를 스킬로 굳히기

```bash
you > /learn lockup-feedback
       → birkin이 마지막 turn의 절차를 ~/.birkin/skills/lockup-feedback/
         밑에 SKILL.md로 캡쳐. 다음에 같은 요청을 하면 자동으로 로드해서
         같은 레시피를 따른다.
```

**Morpheus를 통해 birkin이 야간에 스스로 스킬을 작성**하게 할 수도 있음
(아래 참고 — 승인 게이트로 보호됨).

### 4. Morpheus — 야간 자기개선, 아침에 리뷰

```bash
$ birkin daemon --install      # OS 작업 등록 (cron / launchd / schtasks)
                               # 04:00에 Morpheus가 어제를 읽고, 메모리 쓰고,
                               # 스킬 쓰고(자동), cron/shell 자동화 제안은
                               # 큐로 보냄 (리뷰 필요)
$ birkin morpheus --dry-run    # 오늘밤 무엇을 할지 미리보기 — 비용 0
$ birkin review                # 다음 날 아침, 하나씩 승인 / 거절
$ birkin trace <run-id>        # 과거 turn 감사 replay
```

위험 등급이 위험한 제안부터 화면 위에 올린다 (`shell` > `cron` >
`memory`/`skill`). 자동승인 정책 조정은 `birkin permission`.

### 5. Telegram에서 birkin과 대화

```bash
$ birkin setup              # "Telegram 봇 연결?"에 yes, 토큰 paste
$ birkin gateway            # 이제 Telegram 봇이 터미널 세션과 같은 vault·스킬
                            # 공유
```

---

## 📟 명령어 cheat sheet

```bash
birkin                              # 채팅 시작 (첫 실행 → 온보딩)
birkin chat --dry-run -m "…"        # 프롬프트 패킷 출력 — 모델 호출 없음
birkin runs                         # 최근 run record + 사용량 (감사 로그)
birkin trace <run-id>               # 단일 run record (replay 형식)
birkin budget                       # 일/월 한도 대비 토큰 사용량
birkin setup                        # 온보딩 위저드            (alias: onboard)
birkin model                        # 모델 선택 (API + 로컬 CLI 에이전트)
birkin tools  [--enable/--disable]  # 도구 카탈로그 + 토글
birkin skills                       # 목록  (`<name>`로 출력, `sync`로 미러)
birkin skills validate [--verbose]  # SKILL.md 린트 + 번들 스크립트 py_compile
birkin gateway                      # 서비스 모드 (HTTP + Telegram 채널)
birkin web                          # 모니터링 대시보드
birkin daemon  [--install]          # Morpheus + cron 스케줄러
birkin morpheus [--dry-run]         # 지금 Morpheus 자기개선 루틴 실행
                                    # (호환 alias: `birkin nightly`)
birkin review                       # 대기 중인 제안 승인/거절
birkin cron                         # 스케줄된 작업 목록 / --remove
birkin permission [--add/--remove]  # 자동승인 카테고리
              [--access workspace|full]  # CLI 에이전트 접근 권한
```

### 채팅 안 슬래시 명령

자기 문서화 — `/help`로 전체 목록, `/help <name>`으로 상세:

| 그룹 | 명령 |
|---|---|
| **대화** | `/new` · `/retry` · `/undo` · `/compact` · `/clear` |
| **모델** | `/model` · `/models` · `/provider` · `/temp` |
| **스킬** | `/skills` · `/skill <name>` · `/reload` · `/learn` |
| **메모리** | `/memory <query>` · `/remember <text>` · `/vault` |
| **자율** | `/morpheus` (alias `/nightly`) · `/review` · `/cron` · `/permission` |
| **세션** | `/save` · `/load` · `/sessions` |
| **시스템** | `/tools` · `/system` · `/config` · `/update` · `/help` · `/quit` |

---

## 🧠 메모리 상세 (Obsidian vault)

기본 위치: `~/.birkin/vault`. 모든 사실은 출처가 적힌 마크다운 노트:

```markdown
---
title: FlowerPlus GTM
type: project              # person | project | preference | fact | topic | session
created: 2026-05-27
updated: 2026-05-28
confidence: 0.8
polarity: positive         # 또는 "negative" — 알려진 실패 (재확인 필요)
version: 3                 # 낙관적 락: 옛 스냅샷 덮어쓰기 거부
sources: ["session:2026-05-27"]
tags: [marketing, gtm]
---

기업 복지 꽃 구독. 관련 노트:
[[User Research]], [[Outbound Sales Script]].
```

에이전트가 쓰는 도구: `memory_search`, `memory_get_note`, `memory_write_note`
(`polarity`, `expected_version` 인자), `memory_link`. `config.json`에
`evidence_required: true`를 두면 소스 없는 새 노트는 거부.

---

## 🧩 스킬 상세

스킬은 `SKILL.md`(YAML frontmatter + 마크다운 본문)를 가진 디렉토리,
agentskills.io / hermes 표준과 호환. [`skills/`](./skills) 아래에
**번들 48개** (research, software, writing, data, devops, marketing, …).
직접 만든 스킬은 `~/.birkin/skills/`에 두면 이름 기준으로 번들을 덮어쓴다.

```markdown
---
name: web-research
description: "주제 리서치 후 출처 있는 요약 합성."
version: 1.0.0
license: MIT
metadata:
  birkin:
    tags: [research, web]
---

## When to Use
…
```

**작성.** `load_skill`이 필요한 시점에 본문을 가져옴. `create_skill` /
`improve_skill`은 모든 쓰기를 승인 게이트로 보냄 (Skill-PR 모드) — 번들 스킬은
*원본 자리에서 절대 수정 안 됨*; 먼저 user 디렉토리로 fork. 스킬 저장 없이
복잡한 turn이 지나면 birkin이 스스로 "이거 스킬로 만들까?" nudge (LLM 추가
호출 없음).

**위생.** `birkin skills validate`가 frontmatter 린트 + 번들 `*.py` 전부
`py_compile`. CI에서 활용: 오류 있으면 non-zero exit.

**신선도와 규모.** `SKILL.md`를 편집하면 **hot-reload** (재시작 없음).
frontmatter에 `prerequisites`(commands / platforms)를 추가하면 그 스킬은
**gated** — 전제 미충족이면 카탈로그·라우터에서 숨김. `birkin skills sync`는
업스트림 스킬 트리를 `~/.birkin/skills/mirrors/`에 미러 (번들 스크립트 + 출처
표기 보존). 워크스페이스에 `SOUL.md` / `AGENTS.md` / `TOOLS.md`가 있으면 시스템
프롬프트에 layered됨.

---

## 🌙 Morpheus — 야간 자기개선 & 승인 게이트

그리스 꿈의 신. 네가 자는 동안 birkin이 하루를 리뷰한다.

`birkin daemon` (또는 `birkin daemon --install`로 OS 작업 등록). 설정한
시간(기본 **04:00**)에 Morpheus가:

1. **최근 24h 읽기** — 저장된 대화 + 변경된 파일.
2. **메모리 갱신** — 새 엔티티·사실·`[[link]]`.   *(자동)*
3. **스킬 작성/개선** — 반복 패턴 발견 시.       *(자동)*
4. **제안** — 자동화(cron, 다이제스트, 명령).    *(리뷰)*

안전·되돌릴 수 있는 변경(메모리, 스킬)은 자동 적용. 무인 루틴은 *코드 수준에서*
shell / subagent 도구 없이 동작 — 사고 칠 권한 자체가 없음. 자동승인 조정은
`birkin permission --add cron` (또는 `/permission`). 기본 자동승인은
`memory`, `skill`.

**토큰 예산 거버너** (`birkin budget`) — 일/월 윈도우에서 ledger의 `estTokens`
합산해서 한도 초과 turn은 명확한 메시지로 거부. **침묵 지출 0**.

---

## 🛰️ Gateway & 📊 Dashboard

`birkin gateway`는 에이전트를 영속 서비스로 실행. 모든 채널이 하나의 메모리
vault와 스킬 카탈로그를 공유해서, birkin은 어디서든 너를 기억함:

- **HTTP** (기본 켜짐): `POST /message {"session","text"} → {"reply"}`,
  `GET /health`. localhost 바인딩.
- **Telegram** (선택): `birkin setup`이 안내. 또는 `config.json`의
  `channels.telegram`에 직접 설정. stdlib 기반 long-polling.

`birkin web`은 로컬 **모니터링** 대시보드 (채팅 아님): 실시간 상태, 스케줄
/실행 중 작업, 최근 run, 대기 중 승인 (위험 등급 뱃지 + 승인/거절), 스킬
카탈로그. localhost + per-session 토큰 + Host 체크.

---

## ⚙️ 설정

모든 상태는 `~/.birkin` 아래 (override: `BIRKIN_HOME`):

```
~/.birkin/
├── config.json     # provider, model, vault, Morpheus 시간, 권한…
├── vault/          # Obsidian 시멘틱 메모리 (마크다운 노트)
├── skills/         # 사용자·에이전트 작성 스킬
├── sessions/       # 저장된 대화  (Morpheus 입력)
│   └── repl_history.txt           # 영속 ↑/↓ 명령 히스토리
├── runs/           # turn별 + Morpheus run 요약 (대시보드)
├── ledger.jsonl    # append-only 한 줄 감사 로그
├── pending/        # 승인 대기 중인 제안
├── cron.json       # 등록된 일일 작업
└── status.json     # daemon 하트비트 / 다음 실행 시간
```

`config.json` — 실제로 만질 키들:

```json
{
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "subagent_model": "claude-haiku-4-5-20251001",
  "base_url": "",
  "vault_path": "",
  "morpheus_hour": 4,
  "auto_approve": ["memory", "skill"],
  "budget_tokens_daily": 0,
  "budget_tokens_monthly": 0,
  "evidence_required": false,
  "gateway_port": 8788,
  "web_port": 8787,
  "channels": {
    "http": {"enabled": true},
    "telegram": {"enabled": false, "token": ""}
  }
}
```

API key는 환경변수 우선; CLI-에이전트 provider는 키 불필요. `config.json`에
쓰인 키는 `chmod 600`으로 저장됨 (POSIX).

---

## 🛠️ 현재 상태

- **277개 테스트** 오프라인·API key 없이 통과, `pytest-cov`가 **≥75%**
  커버리지 강제. 현재 커버리지 **76.06 %**.
- **번들 스킬 48개**, 전부 `birkin skills validate` 통과.
- 하드닝 H2 ~ H7 완료 (라이브 LLM 검증 harness, 신뢰성 컨트롤 플레인,
  검증된 학습, Memory OS, 스킬 무결성, 라인 에디터 — 멀티라인 + Kitty
  Keyboard Protocol을 통한 Shift/Ctrl/Alt+Enter).
- 출처 기반 hermes-agent / openclaw 비교: [`docs/COMPARISON.md`](./docs/COMPARISON.md).

로드맵: [`docs/HARDENING-PLAN.md`](./docs/HARDENING-PLAN.md). 결정별 근거:
[`docs/DECISIONS.md`](./docs/DECISIONS.md). 실시간 상태:
[`docs/STATUS.md`](./docs/STATUS.md).

---

## 📄 라이선스

이중 라이선스: **birkin Python 패키지**(`birkin/`, 런타임 코드)는
**Proprietary — All Rights Reserved** (© 2026 ashmoonori). 소스는 검토용으로
공개되지만, 서면 허가 없이는 사용/복사/수정/배포/상업적 권리가 부여되지 않음.
**번들 스킬 카탈로그**(`skills/`)는 **MIT 라이선스** — NousResearch/hermes-agent
와 openclaw의 카탈로그 스타일을 따랐고 일부는 포팅했으므로 상위 MIT 조건과
어트리뷰션을 그대로 보존. 런타임에 `birkin skills sync`로 가져온 스킬은
상위 라이선스 유지. 상세: [`LICENSE`](./LICENSE), [`NOTICE`](./NOTICE).
