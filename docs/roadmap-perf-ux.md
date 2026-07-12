# birkin 성능·UX 개선 로드맵

*2026-07-12. 3중 조사의 종합: ①재리뷰(수정 검증 + 경합 1건 발견·수정 완료),
②외부 딥리서치(에이전트 104개: 검색 5각도 → 소스 fetch → 주장당 3표 적대
검증 — 8개 검증 발견), ③코드 근거 내부 스캔(12개 기회, file:line 근거).
우선순위 = 두 트랙이 수렴하는 지점 > 단일 트랙 고신뢰 > 보류.*

## P0 — 즉시 (리스크 제거 + 수렴 지점)

### P0-1. 편집-스트리밍 레이트리밋 하드닝 ⚠ 신규 리스크
- **근거(외부, 3-0 검증)**: Telegram의 editMessage/sendMessage 예산은 **공유**
  이며, 타이머 기반 반복 편집은 "나쁜 행동 패턴"으로 의도적 스로틀링 대상
  (TDLib 메인테이너 확인, github.com/tdlib/td/issues/3034).
- **현황**: 방금 출고한 `_Streamer`는 1.5s 고정 스로틀 + 429 `retry_after`
  미준수 — 장문 스트리밍에서 차단 리스크.
- **작업**: 내용 변화 임계치 결합 코얼레싱 + 429 응답의 retry_after 백오프.
  노력 S. stdlib.

### P0-2. 승인 인박스 원격화 — 인라인 버튼 원탭 승인
- **수렴**: 내부 #3(승인이 CLI 전용 — `birkin review`) × 외부 #1(인라인
  버튼은 채팅 클러터 없는 callback query, 3-0 검증; answerCallbackQuery
  미호출 시 1분 로딩 애니메이션 함정 문서화됨).
- **작업**: `/pending` 목록 + 제안별 [승인|거부] 인라인 키보드 +
  `answerCallbackQuery` + 처리 후 같은 메시지 편집으로 상태 표시.
  신뢰 채널 게이트(_PRIVILEGED_COMMANDS 규칙) 필수. 노력 M. stdlib
  (sendMessage reply_markup + 2개 API 호출 추가).
- **효과**: propose→approve→act 루프가 폰에서 완결 — birkin 자동화의
  마지막 마일.

### P0-3. Morpheus 야간 요약 배달
- **수렴**: 내부 #2(요약이 print만 됨; `_deliver`+`[SILENT]` 인프라가 cron
  전용으로 이미 존재) × 외부 #5(OpenClaw HEARTBEAT_OK sentinel 억제 —
  "할 말 없으면 침묵" 패턴 3-0 검증).
- **작업**: Morpheus 종료 시 요약+제안 개수를 deliver_chat_id로 전송,
  변화 없으면 [SILENT]. 노력 S-M.
- **효과**: "밤새 스스로 개선"이 아침 다이제스트로 가시화.

## P1 — 다음 (체감 지연·투명성)

### P1-1. REPL의 게이트웨이 패리티 (웜 세션 + 스트리밍 + 마크다운)
- **근거(내부 #1/#4/#6)**: REPL은 CLI 프로바이더에서 **매 턴 콜드스타트**
  (runtime.py:69-73 → 신규 `claude -p`); OpenAI 계열(OpenAI/Gemini/Ollama)
  스트리밍 전무(llm.py:596-608 stream:false); `ui.render_markdown` 데드코드
  — 터미널에 raw `**` 노출. 외부 #4가 TTFT 지배를 3-0 확인.
- **작업**: (a) REPL에 SessionPool/ClaudeStreamSession 재사용(인프라 존재),
  (b) OpenAI SSE 스트리밍, (c) 스트림 종료 후 마크다운 재렌더. 노력 M×3.
- **효과**: REPL 턴 ~10s → 2-3s (게이트웨이와 동급).

### P1-2. 메모리 투명성 라인 (= 안전 장치)
- **수렴**: 내부 #5(기억/회상이 사용자에게 완전 불가시 — "no, forget that"
  불가) × 외부 #8(파일 기반 메모리에서 memory-induced jailbreak 16.8%,
  tool-call drift 62.9% 실측 — **회상 투명성은 UX가 아니라 신뢰 경계**).
- **작업**: 메모리 툴 tool_end에 `🧠 remembered [[X]]` / `🧠 recalled 3
  notes` 컴팩트 라인 — REPL + Telegram 스트림 양쪽. 노력 M.
- **효과**: 핵심 차별점 가시화 + 오염 기억의 사용자 검출 경로.

### P1-3. 침묵 구간 제거 묶음 (퀵윈 3종)
- 내부 #7(재시도 침묵 — "rate-limited, retrying 2/4"), #8(Telegram raw
  예외 → 친화 메시지+서버 로그), 외부 #4("툴 호출 중 무표시 정지는 스톨" —
  스트림에 '검색 중…' 상태 라인). 노력 S×3.

### P1-4. 온보딩 퀵윈 (신규 사용자 첫 5분)
- 내부 #9(/start가 명령 덤프 → 환영+예시), #10(무료 경로 claude-cli가
  프로바이더 목록에서 숨겨짐 → 1급 노출), #12(oauth/onboarding 테스트 0 →
  스모크 테스트). 노력 S×3.

## P2 — 조사 후 (외부 의존/제약 확인 필요)

### P2-1. 멀티모달 수신 (음성·사진·위치)
- 외부 #6 (3-0): 수신·다운로드는 Bot API+stdlib로 즉시 가능(음성 OGG,
  getFile 20MB). **STT/TTS 엔진은 외부 API 필수** — zero-dep 위반이라
  프로바이더 오디오 API(HTTP-only) 경유가 유일한 정합 경로. 1단계로
  "사진/음성 수신 → 파일 저장 + 에이전트에 경로 전달"만 stdlib 구현 가능.
- 모바일 체감 최대 후보이나 의존성 결정 필요 → 사용자 결정 대기.

### P2-2. 프롬프트 캐싱 전략
- 외부 #3 (3-0): 비용 41-80%↓, TTFT 13-31%↑ (Claude ~78%/~21%, arXiv
  2601.06007). 단 claude-cli 경유 시 캐시 제어권이 CLI에 있음 — API 경로
  (Anthropic/OpenAI 직접) + 야간 Morpheus에서 실익. 나이브 전체-컨텍스트
  캐싱은 역효과 사례 있음(검증됨) → 시스템프롬프트+스킬 프로즈 안정 접두부
  설계로 한정. 노력 M, 측정 게이트 필수.

### P2-3. `/remind` — 채팅발 스케줄 (proactivity 전면 개방)
- 내부 #11: cron+deliver+[SILENT] 인프라에 채팅 쪽 문이 없음. 외부 #5의
  sentinel 억제 규칙 적용. 신뢰 채널 게이트 + cron 승인 정책과 정합 필요
  (자동화가 자동화를 만드는 경로라 안전 검토 선행). 노력 M.

## P3 — 보류 (근거 부족 또는 중복)

- **Leon식 3계층 메모리 스코프** (외부 #7): Mnemosyne은 이미 zone·polarity·
  TTL·protected·decay를 가짐 — "daily" 스코프 개념만 신규인데 실익 미검증.
  real-vault 교훈("구조는 움직여도 top-k는 안 움직인다")에 따라 벤치 없이
  도입 안 함.
- **하트비트 상시 턴** (외부 #5의 30분 주기): LLM 상주 비용 vs 이득 미검증
  — P0-3(야간 다이제스트) + P2-3(/remind)로 충분한지 먼저 관찰.

## 근거 출처 (외부 트랙 — 적대 검증 통과분)

- Telegram Bot API/Features 공식 문서 (인라인 버튼·callback·멀티모달 수신)
- TDLib #3034 (levlam: 편집/전송 예산 공유, 반복 편집 스로틀링)
- arXiv 2601.06007v2 (프롬프트 캐싱 500+ 세션 실측)
- AWS Well-Architected Agentic AI Lens (체감 지연 = TTFT + 진행 표시)
- OpenClaw heartbeat 문서 (HEARTBEAT_OK sentinel 억제), Khoj 자동화 문서
- Leon 2.0 (SQLite FTS5 3-scope 메모리)
- 메모리 신뢰 경계 실측 연구 (jailbreak ASR 16.8%, drift 62.9% — 파일 기반)
