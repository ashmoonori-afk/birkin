# Birkin Workbench UI — Design Contract

작성일: 2026-08-13 · 브랜치 `feat/ui-workbench` · 선행 문서: [REFERENCE_ANALYSIS.md](REFERENCE_ANALYSIS.md)

## 1. 사용자 문제

Birkin은 여러 에이전트를 띄우는 터미널이 아니라, **사용자가 에이전트의 작업과 근거를 이해하고 위험한 행동을 승인하거나 중단할 수 있는 개인용 agent workbench**다. 현재 UI의 핵심 결함:

1. **주의 배분 실패**: `/dash`는 5개 고정 패널(세션/에이전트/크론/승인/기억)을 동등하게 나열한다. 승인 대기 항목이 크론 목록과 같은 시각적 무게를 갖는다. 사용자가 "지금 무엇이 내 판단을 기다리는가"를 찾으려면 전 패널을 스캔해야 한다.
2. **대화와 운영 정보의 뒤섞임**: REPL은 도구 이벤트를 대화 흐름에 인라인으로 흘려보낸다. 긴 도구 출력이 대화의 시선 앵커를 파괴한다.
3. **승인 맥락 결핍**: `/pending` 목록과 WebUI 승인 카드는 제목·설명만 보여준다. 요청 주체, 예상 영향, 만료 시간, 거부 시 결과, 관련 근거가 없어 사용자가 맹목 승인하거나 REPL로 돌아가 맥락을 재구성해야 한다.
4. **상태 의미의 표류**: approvals 14종, jobs 5종, agentruns 4종, goals 3종의 raw 상태 문자열이 각 표면에서 제각기 렌더된다. 같은 "멈춤"이라도 사람 대기·의존 대기·오류를 색 하나로 뭉갠다.
5. **재진입 부재**: UI가 재시작되면 무엇이 실행 중이었는지 화면이 알려주지 않는다(상태는 파일에 있으나 UI가 복구 절차를 제공하지 않음).

## 2. 디자인 원칙

1. **Attention before information** — 첫 화면은 정보의 지도가 아니라 주의의 대기열이다. 정렬 기준은 항상 `uistate.attention_rank`.
2. **Conversation is sacred** — 대화 로그는 append-only 라인 플로우(기존 정체성 계승). 운영 상세는 대화에 섞지 않고 점진 공개한다.
3. **Redundant state** — 상태는 글리프 모양 + 색 + 위치로 항상 전달하고 상세면에서 라벨을 추가한다. compact Ledger에서도 색 단독 전달은 금지한다(NO_COLOR/ASCII 대응).
4. **UI proposes, Python disposes** — UI는 실행 권한이 없다. 모든 조작은 authority(Python)에 대한 요청이고, 화면 상태는 authority 응답 후에만 전이된다.
5. **Zero new runtime deps** — 순수 ANSI + stdlib(기존 원칙 계승). 프레임워크(curses/rich/textual) 도입 금지.
6. **Evidence is first-class** — 도구 실행·승인·메모리 변경은 "무엇을 근거로"가 항상 한 번의 상호작용 안에 있다.

## 3. 정보 구조 (Birkin 고유 명칭)

```
┌───────────────────────────────────────────────────────┐
│ Ledger(신호 레일)  │  Bench(작업면)                    │
│  주의 대기열        │   Conversation | Trace | Plan |   │
│  세션/워커/잡       │   Approvals | Evidence | Memory   │
│                    ├───────────────────────────────────┤
│                    │  Loupe(맥락 렌즈, 선택적)          │
├───────────────────────────────────────────────────────┤
│ Composer + Pulse(상태 맥박)                            │
└───────────────────────────────────────────────────────┘
```

- **Ledger** (Signal Rail): 승인/입력 대기 → 실패·만료 → 실행 중 → 예약(잡) → 최근 완료 순의 평탄화된 attention 리스트. 세션·워커·크론·승인을 하나의 정렬 축으로 통합. 데몬 연결 상태 상시 표시.
- **Bench** (Work Surface): 선택된 작업의 심층 화면. 모드: Conversation / Activity(tool trace) / Plan / Approvals / Evidence / Memory. 기본은 Conversation+핵심 결과, 도구 상세는 접힘.
- **Loupe** (Context Lens): 현재 목표, plan 진행, 워커 트리, 승인 위험도·만료, 사용 중 memory/evidence, 모델·토큰·비용, checkpoint. wide=우측 패널, medium=오버레이, narrow=독립 화면.
- **Composer + Pulse**: 테두리 없는 1행 입력면 + 상단 1행 상태 맥박(모드, streaming/paused/approval-required/offline, 대기 승인 수, 모델, 비용). 취소·steer·approve 동작의 화면 내 힌트 상시 표시.

## 4. State model

단일 소스: `birkin/uistate.py` (JSON Schema `uistate.schema()`로 내보냄, TS/웹은 생성 소비만).

| state | glyph | ascii | label | color role | attention |
| --- | --- | --- | --- | --- | --- |
| waiting_human | ◆ | ! | 응답대기 | waiting_human | 0 |
| failed | ✗ | x | 실패 | failure | 1 |
| expired | ⊘ | * | 만료 | warning | 2 |
| unknown | ? | ? | 불명 | warning | 3 |
| running | ▸ | > | 실행중 | running | 4 |
| waiting_dependency | ◇ | o | 의존대기 | waiting_dependency | 5 |
| paused | ∥ | = | 일시정지 | muted | 6 |
| idle | · | . | 유휴 | muted | 7 |
| completed | ✓ | + | 완료 | success | 8 |

런타임 raw 상태 매핑(전량 코드 검증 완료):

- approvals: pending→waiting_human(만료 시각 경과 시 expired), claimed/approving/executing/resuming→running, resume_pending→waiting_dependency, approved/completed/rejected→completed, error→failed, expired→expired, interrupted→paused(재개 가능 중단)
- jobs: queued→waiting_dependency, running→running, succeeded→completed, failed→failed, cancelled→completed(의도된 종결)
- agent runs: running→running, done→completed, error→failed, **stale→unknown**(하트비트 소실 — 생존을 추측하지 않음)
- goals: active→running, paused→paused, done→completed
- moirai: running→running, completed→completed, error/aborted→failed
- 미인식 문자열 → **unknown** (UI가 상태를 창작하지 않음)

**Backend contract 제안**(현 런타임에 없는 것): ① stale run의 생존 판별을 위한 워커 liveness ping 계약, ② waiting_dependency의 "무엇을 기다리는가"(dependency id) 필드, ③ 파일 폴링 대체용 이벤트 스트림(SSE). UI는 이것들 없이도 unknown/폴링으로 정직하게 동작한다.

## 5. Layout breakpoints

터미널(컬럼 기준):

| 레이아웃 | 조건 | 구성 |
| --- | --- | --- |
| Wide | ≥120 | Ledger(34) + Bench + Pulse + 상시 키 힌트 |
| Medium | 80–119 | 80–99는 glyph rail(4), 100–119는 제목 Ledger + Bench + Pulse |
| Narrow | <80 | 상단 Pulse + 단일 전체 폭 Attention Queue; 승인·세션 선택은 별도 화면 |

검증 크기: 60×20, 80×24, 120×30, 160×40. 3열의 단순 압축 금지 — narrow는 별도 구성.

WebUI(px): 375(모바일: 스택+drawer) / 768(2열: Ledger 접이식) / 1024(2열+Loupe 오버레이) / 1440(3열). 동일 상태 계약·우선순위, 레이아웃은 독자적.

## 6. Component inventory

`birkin/uikit.py` (순수 함수, width/color/ascii 인자, 반환 = 문자열 라인):
badge · session_row · approval_card · tool_summary · tool_detail(접힘/펼침) · composer · status_pulse · worker_tree · empty_state · error_state · disconnected_state. 이후 화면(Overview/Bench/Approval/Evidence)은 이 부품만 조립한다.

## 7. Semantic tokens

`birkin/ui_tokens.py`: surface, surface_elevated, text_primary, text_muted, accent, running, waiting_human, waiting_dependency, success, warning, failure, evidence, memory, diff_add, diff_remove, focus, selection. ANSI는 hex에서 파생(단일 소스), WebUI는 `to_json()` 소비. brand accent(황동)와 failure(적)는 분리.

### 시각 방향 비교 (component showcase로 검증)

| 기준 | atelier(황동) | observatory(남색) | jade(옥) |
| --- | --- | --- | --- |
| text/surface 대비 | 15.16 | 15.47 | 15.42 |
| 상태 토큰 최저 대비(≥3 필요) | 4.14 | 4.61 | 4.30 |
| accent-의미색 충돌 | warning과 15° 근접(완화: warning을 주황으로 이동) | memory 보라와 충돌 | **success 초록과 충돌(치명)** |
| 참조와의 차별성 | Gajae 적/주황·Herdr와 구분됨 | 보라 계열 흔함 | 초록 계열 흔함 |
| 제품 정체성 | 장인의 작업대·황동 공구 = workbench 서사 일치 | 야간 관제 서사 | 저자극 모니터링 |

**선택: atelier.** 근거: 의미색 충돌이 가장 작고(완화 적용), 두 참조와 시각적으로 구분되며, workbench 제품 서사와 일치. 나머지 두 방향은 코드에 보존(사용자 테마 전환 여지).

## 8. Interaction model

- 입력 등가성: 모든 조작은 키보드로 가능, 터미널 마우스 클릭(지원 시)과 WebUI 클릭은 같은 액션에 수렴.
- 점진 공개: tool_summary(1행) → tool_detail(높이 상한+오버플로 마커). 실행 중 카드 높이 고정, 완료 시에만 갱신(스트리밍 안정성). 이 surface는 원본 전체 보기 동작을 제공하지 않는다.
- 승인 흐름: 모든 카드에 요청 주체·동작·거부 결과를 표시하고, authority record가 제공하는 대상·예상 영향·위험도·만료·근거를 추가 표시한다. approve 입력 → "요청 전송" 표시 → authority 성공 응답 후에만 완료 전이. 파괴적 작업은 approve와 execute 단계 분리 표기. 재연결 시 전 승인 재조회.
- 오류/재접속: disconnected_state는 항상 복구 명령을 화면에 인쇄(reattach 원칙).

## 9. Keyboard map (초안, Birkin 명령 수 기준 — prefix key 불채택)

Birkin slash 명령은 ~20개로 tmux급 충돌이 없다. 단일 키 + 수식키 체계:

| 키 | 동작 |
| --- | --- |
| `j/k` 또는 `↑/↓` | 리스트 탐색 |
| `Enter` | 선택 항목 열기 |
| `Space` | tool detail 접기/펼치기 |
| `a` / `r` | (승인 포커스) approve / reject — 항상 확인 단계 경유 |
| `f` | authority snapshot 새로고침 |
| `?` | 그룹형 도움 오버레이 |
| `Esc` | 오버레이 닫기 / 스트리밍 취소(기존 계승) |
| `q` | 대시보드 종료(기존 계승) |

핵심 키는 화면 하단에 상시 노출하고 전체 키맵은 `?` 오버레이에 노출한다. `/work`는 읽기/승인 workbench이며 대화 입력은 기존 `/chat` surface가 소유한다.

## 10. 원본성·라이선스

- Gajae-Code(MIT), Herdr(Apache-2.0)에서 **코드 복사 없음** — 원칙만 재구현(REFERENCE_ANALYSIS.md §2). 로고·문구·팔레트 hex·아이콘 조합·패널 비율·컴포넌트명 미사용.
- 색상값은 본 문서에서 신규 정의(WCAG 대비 계산 근거). 글리프는 Unicode 표준 문자 조합이며 Herdr의 세트(×◐✓○·)와 다른 조합(▸◆◇·∥✓✗⊘?)을 사용.
- 향후 코드 차용 발생 시 NOTICE와 변경 고지 의무 이행(Apache-2.0), 현재 해당 없음.

## 11. 선택하지 않은 대안

| 대안 | 기각 사유 |
| --- | --- |
| TypeScript/Ink 기반 TUI 재작성 | 새 core runtime dep + 이중 런타임. 기존 zero-dep ANSI 정체성 파괴. presentation층 TS는 WebUI에 한정 |
| Rust 멀티플렉서(Herdr식) 도입 | Birkin에 pane/PTY 소유권 개념 부재. 범용 멀티플렉서화는 제품 정의 위반 |
| tmux식 prefix key | 명령 수(~20)가 정당화하지 못함. 발견성 저하 |
| WebSocket 실시간 push | 현 런타임에 이벤트 버스 없음. 폴링 유지 + SSE를 backend contract로 제안만 |
| 5패널 dash 유지·개선 | 주의 배분 실패의 원인 구조. 부분 개선 불가 판단 |
| jade/observatory 방향 | §7 비교표 — accent-의미색 충돌 |
| 대화·이벤트 단일 스트림(현 REPL 방식 유지) | 원칙 2 위반. 도구 상세는 점진 공개로 이동 |

## 12. 테스트·QA 계약

- viewport regression: uikit 컴포넌트와 화면 조립을 4개 터미널 크기에서 순수 함수로 렌더하고 폭·핵심 내용을 검사.
- CJK: 모든 폭 계산은 `ui.cell_width` 경유, 한글 혼합 케이스가 각 컴포넌트 테스트에 포함.
- NO_COLOR/ASCII: escape 0개 보장 + ascii_only 글리프 세트.
- 권한 경계: UI 모듈은 shell/tool executor를 import하지 않는다. 승인/거부는 확인 후 `resolve_approval()` adapter가 Python authority를 호출하고, UI는 authority 응답 후 snapshot을 다시 읽는다.
- 시각 QA 증거: 터미널 60×20/80×24/120×30/160×40 실 렌더의 전체 line set과 폭 측정, WebUI 375/768/1024/1440 전체 화면 스크린샷.

### 이번 surface의 명시적 비범위

- Loupe와 Composer **컴포넌트 계약**은 후속 채팅 surface 통합을 위해 남아 있지만, 이번 `/work` TUI 조합에는 포함하지 않는다. 실행 가능한 terminal 범위는 Ledger/Bench/Pulse, 세션 tool trace, 승인 상세, 도움말이다.
- `birkin dash`는 기존 호환 surface이며 이 계약의 상태 통합 대상이 아니다. 단일 `UIState` 계약은 새 `/work`와 Web workbench에 적용된다.
- 터미널 증거는 ANSI/CJK 폭을 계산한 전체 frame 출력이다. PTY 이미지 golden은 현재 저장하지 않으며 이를 snapshot coverage로 주장하지 않는다.
