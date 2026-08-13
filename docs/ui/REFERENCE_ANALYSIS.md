# UI Reference Analysis — Gajae-Code / Herdr → Birkin

작성일: 2026-08-13 · 브랜치: `feat/ui-workbench`

## 0. 조사 기록 (Audit)

| 항목 | 값 |
| --- | --- |
| Birkin HEAD (origin/main) | `cb017a94cdc37226f74a993d6deeae0ae0a7a65b` |
| Gajae-Code HEAD | `d915ffe58edddba8cb5f9cb9393b1943ebb6cc5c` (MIT) |
| Herdr HEAD | `952729ee03e0939d7a9d893f87f24179cf0eb7cb` (Apache-2.0) |

**현재 Birkin UI 구조** (검증: 2026-08-13, 코드 직접 확인)

- 진입점: `birkin = birkin.cli:main` (pyproject.toml:55). `birkin chat` → `repl.py`(스트리밍 REPL, slash 명령), `/dash` → `dash.py`(순수 ANSI alt-screen 대시보드, `snapshot()`/`render()` 순수 함수, 2초 갱신), `birkin web` → `web/server.py`(stdlib HTTPServer, 단일 `static/index.html` SPA, 15초 polling).
- 상태 생성·전달 경로: 승인 `store.py`(`~/.birkin/pending/*.json`, `add_pending`/`resolve_pending`) + `approvals.py`(pending → approving → executing / resume_pending → resuming → completed, `expires_at` 기반 `expired`); 백그라운드 잡 `background_receipts.py`(`JobStatus = queued|running|succeeded|failed|cancelled`); 서브에이전트 런 `agentruns.py`(`running|done|error|stale`, 하트비트 180s); Moirai `moirai/journal.py`(sqlite, running/completed/error/aborted); 크론 `cron.py`(`cron.json`); 목표 `goals.py`(active/paused/done); 메모리 `memory.py`/`mnemosyne.py`(Obsidian vault); 체크포인트 `checkpoints.py`(bare git, UI 비노출).
- 전송 메커니즘: 전부 파일/DB 폴링. WebSocket/SSE 없음. WebUI 승인 조작은 `POST /api/approvals` 단일 경로 — 실행 권한은 Python이 소유.
- 렌더링 유틸: `ui.py` — `should_color()`(NO_COLOR > BIRKIN_NO_COLOR > CLICOLOR_FORCE > tty), `cell_width()`(East Asian Width, ANSI 제거 후 계산), `fit()`, `pad()`.
- 테스트/패키징: pytest(`-m 'not live'`, 커버리지 게이트 75%), hatch wheel, 콘솔 스크립트 1개. UI 테스트: `test_ui_width.py`, `test_dash.py`(순수 함수 검증) 등.
- 진행 중 작업: `feat/webui-ide-workbench-final`, `feat/structured-action-ux`, `feat/agent-ux-port`는 모두 main에 병합 완료(main..branch = 0 커밋). `feat/frontend-debug-systems`는 skills/docs만 변경. → 본 작업과 충돌 없음. `docs/tui-redesign-plan.md`는 설계 의도 문서(제로 의존성 원칙, append-only 라인 플로우 정체성)로, 본 재설계는 그 제약을 계승한다.

## 1. 참고 요소 분석표

평가 축: **정보 밀도 / 시선 흐름 / 상태 인지 / 작업 전환 비용 / 오류 예방** (미관 표현 금지).

| Reference | 해결하는 문제 | 추출할 원칙 | Birkin식 재해석 | 가져오지 않을 요소 |
| --------- | ------------- | ----------- | --------------- | ------------------ |
| Gajae: borderless composer (`welcome.ts:149-250`) | 입력창 주변 장식이 시선을 분산시켜 작성 중 인지 부하 증가 | 콘텐츠 우선·크롬 최소화: 테두리는 레이아웃 제약이 아니라 옅은 장식; content width와 terminal width 분리 | Composer는 1행 프롬프트 마커 + 밑줄 없는 입력면. 모드/상태는 Composer 위 1행 Status Pulse로만 표기 | 이중 컬럼 웰컴 화면 배치, "GJC Forge" 문구·로고·펫 위젯 |
| Gajae: progressive disclosure (`tool-execution.ts:300-650`) | 도구 출력 전체 노출 시 대화 스크롤이 폭발해 핵심 결과로의 시선 복귀 비용 급증 | 공개 여부는 컴포넌트의 boolean 상태; 접힘 상태 줄 예산 고정(출력 4줄), "… N more lines" + 펼침 힌트 | 도구 카드: 이름·대상·결과 요약·소요시간·성공여부·위험여부만 기본 표시. stdout/diff/trace는 펼침 시에만, 높이 상한 + 내부 스크롤 | 12줄/4줄 등 구체 수치의 맹목 복사, JSON 트리 렌더러 코드 |
| Gajae: 접힌 tool summary (`tool-execution.ts:553-595`) | 접힌 상태에서 실패 원인 파악 불가하면 강제 펼침 → 작업 전환 비용 증가 | 제목 줄에 상태·핵심 인자를 항상 보존, 본문만 절단; 구조화 데이터는 고정 깊이 요약 | 요약 1줄 = 심볼 + 도구명 + 대상 + 결과 코드/시간. 실패 시 오류 1줄을 요약에 승격 | 인라인 인자 70자 규칙 등 상수, 컴포넌트 명칭 |
| Gajae: 스트리밍 안정 갱신 (`tool-execution.ts:184-235`) | diff 스트리밍 중 제거줄이 먼저 도착해 화면이 출렁이면 읽던 위치 상실 | 안정 마일스톤까지 버퍼링; 논리 상태 변화 시에만 재렌더; 동일 출력 프레임 재출력 금지 | 실행 중 카드 높이 고정(요약 1줄 + 진행 1줄), 완료 시에만 높이 갱신. REPL append-only 정체성 유지 | Bun/Rust 네이티브 width 코드, 프리뷰 diff 비동기 파이프라인 구현 |
| Gajae: status rail (`presets.ts:8-65`, `segments.ts`) | 모델·비용·상태 확인을 위해 대화 밖으로 나가는 전환 비용 | 세그먼트 = 순수 렌더 함수, 프리셋 = 조합; 시맨틱 색 role 사용 | Status Pulse: 모델·데몬 연결·대기 승인 수·비용·목표 상태를 1행 요약. 기존 `statusline.py` 계승 확장 | 프리셋 7종 구성 그대로, `statusLine*` 토큰명 그대로 |
| Gajae: responsive launch (`welcome.ts:149-200`) | 80컬럼 SSH와 200컬럼 데스크톱에서 같은 화면이 깨짐 | 터미널 종류가 아닌 가용 폭 기준 분기; 각 블록의 최소 폭 선언 후 배치 결정 | 터미널 레이아웃 3단계(wide/medium/narrow)를 폭 임계값으로 결정, 각 영역 최소 폭 미달 시 하위 레이아웃으로 강등 | 웰컴 화면 자체(Birkin은 관제 Overview가 첫 화면) |
| Gajae: command palette + key hints (`command-palette.ts`, `keybinding-hints.ts`) | 명령·단축키 암기 강요는 발견성 결여 → 오류 예방 실패 | 퍼지 검색 + 커서 탐색 + 화면 내 힌트를 테마 role로 통일 | `/` 팔레트 + `?` 도움 오버레이, 화면 하단 상시 힌트 1행 | `/ # ! $` 명령 문법, 키 배정 그대로 |
| Gajae: semantic theme token (`red-claw.json`) | 색상 하드코딩은 테마·NO_COLOR·라이트 지원 시 전 컴포넌트 수정 유발 | 토큰명 = 용도(왜 이 색인가); 팔레트(named hue) → role 매핑 2단 구조 | Python 소유 토큰 레지스트리(`ui_tokens`), role → ANSI/hex 매핑, NO_COLOR 시 심볼·텍스트만으로 성립 | red-claw 팔레트 hex값, 토큰명 문자열, 테마 이름 |
| Gajae: CJK width + visual QA (`utils.ts:317-410`, `ui-design-visual-qa.md`) | 한글 폭 오계산 → 정렬·줄바꿈 파괴; 평문 캡처는 색·배치 회귀를 놓침 | UAX#11 기반 폭 계산, CJK 줄바꿈 파괴는 blocking 결함; QA 증거는 ANSI 보존 + 메타데이터 | 기존 `ui.cell_width()` 계승, 골든 테스트에 한글 혼합 케이스 필수, 스크린샷 증거는 전체 화면 | Bun stringWidth 구현, Thai/Lao 정규화 코드 복사 |
| Herdr: at-a-glance overview (`sidebar.rs:129-166`) | 다중 에이전트 상태 파악을 위해 탭을 순회하는 전환 비용 | 계층을 평탄화한 정렬 가능한 단일 리스트; 상태 심볼+라벨을 시선 앵커로 | Signal Rail: 세션·워커·승인·잡을 하나의 attention 리스트로 평탄화 | AgentPanelEntry 구조체·명칭, pane/terminal 소유 모델 |
| Herdr: 상태의 시각 구분 (`status.rs:201-238`) | 색맹·저대비 터미널에서 색만으로는 상태 인지 실패 | 4중 인코딩: 글리프 모양 + 색 + 텍스트 라벨 + 위치. 모양 자체가 의미(×, ◐, ✓, ○) | 상태별 글리프·라벨·색을 상태 계약에 고정; NO_COLOR/ASCII에서도 글리프·라벨만으로 구분 | 아이콘 조합 그대로, 색상값 |
| Herdr: attention-first 정렬 (`actions.rs:926-932`) | 오래 실행되는 다중 세션에서 "지금 조치할 것"이 묻힘 | 우선순위 = (차단 정도, 신규성). seen 플래그로 확인된 항목은 가라앉힘 | Birkin 정렬: waiting_human > failed > expired > running > waiting_dependency > paused > idle > completed; 최근 완료(unseen)는 completed 상단 | 5단계 u8 수치 자체, seen 저장 방식 |
| Herdr: 접이식 sidebar (`sidebar.rs:752,972`) | 사이드바가 80컬럼에서 본문을 압사시킴 | 밀도는 모달(전개 ↔ 글리프 전용) 이진 토글, 어중간한 부분 축소 금지 | Signal Rail: wide=전개, medium=글리프 열(폭 4), narrow=상단 switcher로 대체 | COLLAPSED_WIDTH=4 등 수치, 드래그 divider 구현 |
| Herdr: workspace→session→pane 계층 (`layout.rs`) | 다중 저장소·다중 세션의 위치 추적 | 인덱스 경로 탐색 + 상위로 상태 집계(bubble-up) | Birkin 계층: 세션 → 워커(agentruns 트리) → 도구 실행. 세션 행에 하위 상태 집계 표시 | worktree/Spaces 개념(비존재), BSP pane 트리 |
| Herdr: 좁은 화면 switcher (`mobile.rs:50-200`) | 좁은 폭에서 사이드바 축소는 판독 불능 | 임계값 이하 → 사이드바 완전 숨김 + 전체 폭 본문 + 온디맨드 모달 switcher | narrow: 상단 1행 switcher(현재 세션 + 대기 수) + 단일 Work Surface + drawer | 96컬럼 임계값 수치, 터치 히트 영역 코드 |
| Herdr: 입력 등가성 (`input/mouse.rs`) | 마우스 전용/키보드 전용 기능은 사용자 절반에게 기능 결손 | 입력원 무관 동일 액션 디스패치로 수렴 | 터미널: 모든 조작 키보드 우선 + 마우스 클릭 동등; WebUI: 역방향 동일 | tmux식 prefix key 모델(무조건 도입 금지) |
| Herdr: 검색형 help overlay (`keybind_help.rs`) | 40+ 단축키 암기 불가 → 기능 사장 | 작업(task) 기준 그룹핑 + 검색; 앱 내 상주 | `?` 오버레이: 작업 그룹별 + 검색, Birkin 명령 수(slash 명령 ~20개)에 맞게 1화면 우선 | 그룹명·키 조합 표기 형식 |
| Herdr: reattach UX (`attach.rs:1627`, `client/mod.rs:274`) | UI 프로세스 소멸 후 실행 중 작업을 찾을 수 없음 | 백엔드=상태 보유 런타임, 클라이언트=일회성 뷰; 재진입 명령을 화면에 인쇄 | Birkin은 이미 파일 기반 상태 → UI 재시작 시 전 상태 재조회로 복구, disconnected 화면에 재연결 절차 표시 | SSH 터널·세션 서버 구현, Rust/PTY/Ghostty 스택 |

## 2. 라이선스 검토

- **Gajae-Code (MIT)**: 코드 미복사. 원칙(토큰 구조, 공개 패턴, 폭 계산 접근)만 재구현. 브랜드(이름·로고·red-claw 팔레트 hex·명령 문법) 미사용.
- **Herdr (Apache-2.0)**: 코드 미복사 — 원칙 재구현 원칙 채택. 만약 향후 코드 차용 시: LICENSE 사본 포함, 저작권 고지 보존, 변경 고지 헤더, NOTICE 반영 필요. 상표(이름·로고) 사용권 없음.
- 본 재설계에서 두 저장소로부터 **복사한 코드 없음**. 참조는 본 문서의 file:line 인용으로 한정.

## 3. 결론: Birkin이 두 참조와 다른 지점

Gajae는 "한 대화를 깊게", Herdr는 "여러 프로세스를 넓게" 본다. Birkin의 사용자 문제는 둘 다 아니다 — **"에이전트가 한 일과 그 근거를 검증하고, 위험한 행동을 승인/중단한다"**. 따라서:

1. 첫 화면은 대화도 pane 그리드도 아닌 **주의 대기열(attention queue)** 이다. 승인 대기·실패가 항상 최상단.
2. 도구 출력보다 **근거(evidence)와 승인 맥락**이 1급 정보다. 두 참조 모두 갖지 않은 축.
3. UI는 실행 권한이 없다. 모든 조작은 Python authority에 대한 **요청**이며, 상태는 authority 응답 후에만 전이된다.
