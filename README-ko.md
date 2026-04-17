<h1 align="center">Birkin</h1>

<p align="center">
  <strong>기억하고, 학습하고, 당신을 위해 일하는 개인 에이전트 OS.</strong>
</p>

<p align="center">
  <a href="#-빠른-시작">빠른 시작</a> &bull;
  <a href="#-birkin이-하는-일">소개</a> &bull;
  <a href="#-9탭-webui">WebUI</a> &bull;
  <a href="#-프로바이더">프로바이더</a> &bull;
  <a href="#-메모리-시스템">메모리</a> &bull;
  <a href="#-자동화">자동화</a> &bull;
  <a href="#-api">API</a> &bull;
  <a href="#-아키텍처">아키텍처</a> &bull;
  <a href="README.md">English</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/version-v0.3.0-green" alt="v0.3.0">
  <img src="https://img.shields.io/badge/tests-461%2B-brightgreen" alt="461+ tests">
  <img src="https://img.shields.io/badge/providers-9-orange" alt="9 Providers">
</p>

---

## Birkin이 하는 일

대부분의 AI 도구는 대화가 끝나면 당신을 잊습니다. Birkin은 다릅니다.

**Birkin은 개인 에이전트 OS입니다.** 당신의 컴퓨터에서 실행되며, 모든 LLM에 연결하고, 모든 대화에서 지식을 축적합니다. 작업에 맞는 최적의 모델을 자동 선택하고, 트리거로 워크플로우를 자동 실행하며, 시간이 갈수록 당신에게 더 잘 맞는 에이전트가 됩니다.

- **하나의 인터페이스, 모든 LLM** — Claude, GPT, Gemini, Perplexity, Groq, Ollama, OpenRouter. Birkin이 각 작업에 최적의 모델을 선택합니다.
- **축적되는 메모리** — 모든 대화가 검색 가능한 위키로 컴파일됩니다. 관련 컨텍스트가 자동으로 주입됩니다.
- **스스로 실행되는 자동화** — 트리거(크론, 파일 변경, 웹훅)를 설정하면 워크플로우가 알아서 실행됩니다.
- **100% 로컬, 100% 당신의 것** — 셀프 호스팅. 클라우드 의존 없음. 데이터는 절대 외부로 나가지 않습니다.

---

## 빠른 시작

### 원클릭 (권장)

**Windows:** `scripts/start.bat` 더블클릭
**macOS/Linux:** `scripts/Birkin.command` 더블클릭 또는 `scripts/start.sh` 실행

브라우저가 `http://127.0.0.1:8321`에서 자동 열림. 첫 실행 ~1분 (venv 생성 + 의존성 설치). 이후 즉시 시작.

### 수동 설치

```bash
git clone https://github.com/ashmoonori-afk/birkin.git
cd birkin
python3 -m venv .venv && source .venv/bin/activate
pip install -e "."
birkin                # WebUI (:8321)
birkin chat           # 터미널 채팅
birkin mcp serve      # MCP 서버 (Claude Code, Cursor 등에서 사용)
```

### API 키 설정

`.env.example`을 `.env`로 복사하고 키 추가:

```bash
ANTHROPIC_API_KEY=sk-ant-...    # Claude
OPENAI_API_KEY=sk-...           # GPT + OpenRouter
PERPLEXITY_API_KEY=pplx-...     # 검색 특화
GEMINI_API_KEY=...              # 멀티모달 + 100만 컨텍스트
GROQ_API_KEY=gsk_...            # 초저지연
```

**API 키 없어도 OK!** Ollama(로컬) 또는 Claude Code CLI를 사용하면 비용 0원.

---

## 9탭 WebUI

| 탭 | 기능 |
|----|------|
| **Chat** | 스트리밍 대화, 도구 호출 시각화, 자동 메모리 저장 |
| **Workflow** | 비주얼 에디터 — 30+ 노드 타입 드래그 앤 드롭 |
| **Memory** | 지식 그래프 — 기억 확인, 페이지 편집, 파일 업로드 (.md, .json, .csv, .pdf) |
| **Telegram** | 3단계 봇 연결 — 폴링 모드 지원 (공개 URL 불필요) |
| **Triggers** | 스케줄 자동화 — 크론, 파일 감시, 웹훅, 메시지 필터 |
| **Skills** | 스킬 플러그인 설치/토글 (code-review, web-summarizer 등) |
| **Dashboard** | 실시간 모니터링 — 토큰 사용량, 지연시간, 에러율 |
| **Approvals** | 안전 장치 — 에이전트 액션 승인/거부 |
| **Insights** | 주간 리포트 — 토큰 사용 추이, 프로바이더 분포, 패턴 감지 |

---

## 프로바이더

Birkin은 작업의 특성, 비용, 속도에 따라 최적의 프로바이더를 자동 선택합니다.

| 프로바이더 | 강점 | API 키 | 로컬? |
|-----------|------|--------|-------|
| **Anthropic** | 추론, 코딩 | `ANTHROPIC_API_KEY` | |
| **OpenAI** | 범용 | `OPENAI_API_KEY` | |
| **Perplexity** | 웹 검색 | `PERPLEXITY_API_KEY` | |
| **Gemini** | 비전, 100만 컨텍스트 | `GEMINI_API_KEY` | |
| **Groq** | 초저지연 | `GROQ_API_KEY` | |
| **Ollama** | 완전 로컬, 무료 | — | O |
| **OpenRouter** | 100+ 모델 | `OPENAI_API_KEY` | |
| **Claude CLI** | Claude Code 로컬 | — | O |
| **Codex CLI** | Codex 로컬 | — | O |

설정에서 `provider: "auto"`로 지정하면 가장 저렴한 적합 모델이 자동 선택됩니다.

---

## 메모리 시스템

Birkin의 메모리는 일반 챗봇과의 결정적 차이입니다.

**작동 방식:**
1. 모든 대화를 LLM 분류기가 평가 (한국어/영어 이중 언어 지원)
2. 중요한 대화는 태그 + 카테고리와 함께 위키 페이지로 저장
3. 다음 대화 시 시맨틱 검색으로 관련 페이지를 찾아 컨텍스트에 자동 주입
4. 참조되지 않는 페이지는 시간이 지나면서 자연스럽게 감쇠 — 가치 있는 지식만 남음

**핵심 기능:**
- 관련성 기반 컨텍스트 주입 (전체 덤프가 아님)
- 20일 반감기 메모리 감쇠 (신뢰도 x 참조횟수 x 시간)
- 프롬프트 인젝션 자동 방어
- 한국어 고유명사 인식 (kiwipiepy 옵션)
- 다국어 위키링크 별칭 시스템
- `wiki_read` 도구로 온디맨드 페이지 조회 (토큰 절약)
- 매일 새벽 3시 자동 컴파일 + 세션 정리

---

## 자동화

### 트리거

| 타입 | 예시 |
|------|------|
| **크론** | "매주 월요일 9시, 지난 주 요약해줘" |
| **파일 감시** | "reports/ 폴더에 변경이 생기면 분석 실행" |
| **웹훅** | "배포 웹훅이 오면 스모크 테스트 실행" |
| **메시지** | "텔레그램에 '긴급' 포함된 메시지 오면 알림" |

### 워크플로우

- **Simple 모드:** BFS 노드 그래프 (30+ 노드 타입, 드래그 앤 드롭)
- **Graph 모드:** 조건 분기, 병렬 실행, 루프, 체크포인트
- **NL 빌더:** 원하는 자동화를 한 문장으로 설명하면 워크플로우를 생성

### 토큰 예산

모든 세션에 예산이 적용됩니다. 토큰이 부족하면 자동으로 컨텍스트를 압축하거나 저렴한 모델로 전환합니다. 예상치 못한 비용 없음.

---

## API

| 그룹 | 엔드포인트 | 용도 |
|------|----------|------|
| **채팅** | `POST /api/chat`, `/api/chat/stream` | 블로킹 + SSE 스트리밍 |
| **세션** | `GET/POST/DELETE /api/sessions` | 대화 관리 |
| **메모리** | `GET/PUT/DELETE /api/wiki/*` | 위키 CRUD + 그래프 + 검색 |
| **트리거** | `GET/POST/DELETE /api/triggers` | CRUD + 수동 실행 |
| **스킬** | `GET/POST /api/skills` | 목록 + 토글 |
| **대시보드** | `GET /api/observability/*` | 사용량, 지연, 에러 |
| **승인** | `GET/POST /api/approvals` | 대기중 액션 |
| **음성** | `POST /api/voice/stt`, `/tts` | 음성→텍스트, 텍스트→음성 |
| **MCP** | `birkin mcp serve` | MCP 서버로 노출 |
| **설정** | `GET/PUT /api/settings` | 설정, 키, 프로바이더 |

15개 라우터, 69개 엔드포인트.

---

## 아키텍처

```
birkin/
  core/           에이전트 루프, 9 프로바이더, 그래프 엔진, 예산, 승인 게이트
  mcp/            MCP 클라이언트 + 서버 + Playwright 브라우저 자동화
  triggers/       크론, 파일 감시, 웹훅, 메시지 + SQLite 영구 저장
  skills/         SKILL.md 플러그인 시스템
  memory/         위키, 이벤트 스토어, 컴파일러, 시맨틱 검색, 감쇠, 인사이트
  eval/           JSONL 평가 프레임워크 (회귀 감지)
  observability/  구조화된 트레이싱 (Trace > Span > JSONL)
  voice/          Whisper STT + TTS
  gateway/        FastAPI 백엔드 (15 라우터)
  web/            9탭 WebUI
  tests/          461+ 테스트 (pytest)
```

---

## 보안

- Shell 도구는 **화이트리스트** 방식 — 읽기 전용 명령만 기본 허용
- Shell 메타문자 (`|`, `&&`, `>`, `` ` ``) 차단
- `BIRKIN_SHELL_ALLOWLIST=curl,python`으로 확장 가능
- 네트워크 노출 전 `BIRKIN_AUTH_TOKEN` 설정 필수
- 메모리 자동 저장 시 프롬프트 인젝션 패턴 자동 필터링

---

## 기여

```bash
pytest tests/ -q          # 테스트 실행
ruff check .              # 린트
ruff format --check .     # 포맷 체크
```

자세한 내용은 [CONTRIBUTING.md](CONTRIBUTING.md)를 참조하세요.

---

## 라이선스

MIT — [LICENSE](LICENSE) 참조.

Copyright (c) 2026 Birkin Team.
