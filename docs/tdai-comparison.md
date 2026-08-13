# birkin/Mnemosyne vs TencentDB-Agent-Memory (TDAI) — 비교와 차용

*2026-07-12. 대상: TencentCloud/TencentDB-Agent-Memory (TS, 8.5k★) —
"4-tier progressive pipeline, fully local, zero external API". 소스·README
정찰 기반; 차용 판정은 birkin 테제(산술 우선·stdlib·안전은 코드로) 필터를
통과한 것만.*

## 1. 구조 비교

| 축 | TDAI | birkin/Mnemosyne | 판정 |
|---|---|---|---|
| 계층 | **L0 대화(md) → L1 원자 사실(JSONL+벡터) → L2 씬(에피소드) → L3 페르소나** — 명시적 4계층 | L0=autosave 트랜스크립트 → 노트(vault, zone 배치) → SOUL.md(수동 페르소나) + identity zone | TDAI가 계층이 명시적; birkin은 L2(에피소드)·L3(자동 페르소나) 부재 |
| 검색 | BM25(FTS5) + sqlite-vec 벡터, RRF 하이브리드 | BM25+바이그램 + decay + zone prior — **측정으로 하이브리드 동급 입증** (§5.1, 튜닝 lexical 0.900/0.977/0.933) | **birkin 우위(증거)** — 벡터 도입 불요 |
| 추출 시점 | **대화 5회마다 / 유휴 600s** (준실시간, LLM) + 워밍업 스케줄(1→2→4) | 야간 1회 (Morpheus) | TDAI가 당일성 우위 — 단 birkin은 session_search/session_get(ADR-041)로 당일 회상 가능 → 격차 부분 상쇄 |
| 중복/충돌 | **쓰기 시점 2단계**: 기계적 후보 검색(벡터→FTS5 강등) → LLM 배치 판정 | 야간 Morpheus가 duplicate/contradiction/supersede 판정 | **차용 A**: 기계적 후보 검색을 쓰기 시점 *어드바이저리*로 — LLM 판정은 야간 배치 유지 (비용 0 추가) |
| 망각 | 없음 (보존+추적성 중심; retention 0=영구) | Ebbinghaus decay + 아카이브 티어 (벤치마크 검증, H5) | **birkin 우위(증거)** |
| 안전 | 앱이 직접 씀 (화이트박스 아티팩트로 보완) | **CurationPlan/2**: 모델은 계획만, executor가 불변식 강제 | **birkin 우위** |
| 추적성 | 추상→원본 drill-down 체인, 모든 중간물 가독 아티팩트 | `source:` frontmatter + evidence gate + SHA 감사 | par |
| 컨텍스트 관리 | Mermaid 심볼 그래프 오프로딩(50%/85% 임계) | 토큰 다이어트(스니펫 미리보기 + on-demand 전문, 실측 371×) | 접근 다름; birkin은 측정 기반 |

## 2. 차용 판정

### 차용 A — 쓰기 시점 근접중복 가드 (구현: 2026-07-12)

TDAI의 2단계 dedup에서 **1단계(기계적 후보 검색)만** 가져온다. LLM 판정
단계는 이미 Morpheus 야간 배치가 하고 있으므로, 쓰기 시점에는 **비용 0의
어드바이저리**가 정확한 birkin식 번역이다:

- `memory_write_note`가 쓰기 직후, 새 노트의 토큰 집합과 기존 인덱스
  `terms`(이미 있음 — 추가 I/O 없음)의 코사인으로 근접 노트를 탐지.
- sim ≥ 0.60 → "거의 중복 — supersede/append 고려" 힌트,
  0.35 ≤ sim < 0.60 → "관련 노트 — memory_link 고려" 힌트를 툴 결과에 부가.
- **차단하지 않는다** (never-surprise): 쓰기는 항상 성공하고, 힌트는 쓰는
  에이전트에게, 최종 판정은 야간 Morpheus에게. TDAI의 "충돌 검출 불가 시
  전부 저장" 강등 철학과도 일치.

### 보류 B — L2 에피소드(씬) 노트

"무슨 일이 있었나" 단위의 씬 집계는 multi-session/temporal 질의(우리 약점
유형: preference 0.867, temporal 0.953)에 도움이 될 *수 있으나*, real-vault
실험의 교훈("구조는 바뀌어도 top-k는 안 움직인다")이 경고한다 — 에피소드
노트가 검색을 실제로 개선하는지 **벤치마크 없이 도입하지 않는다**. 도입
시점: LongMemEval multi-session 유형으로 A/B 가능해질 때.

### 보류 C — L3 자동 페르소나 (50 기억마다 재생성)

SOUL.md는 사용자 소유 문서라 자동 덮어쓰기는 금지. birkin식 번역은
"Morpheus가 identity zone에 `user-profile` 노트를 **제안**"인데, 이는
Morpheus 스킬 프롬프트 변경이라 별도 세션의 프롬프트 작업으로 보류.

### 기각 D — sqlite-vec 벡터층

우리 실측이 답: 튜닝 lexical이 하이브리드 동급(0.900/0.977/0.933), 벡터는
런타임 의존성 추가. zero-dep 모트 유지.

### 기각 E — 준실시간 추출(5턴/600s 유휴 트리거)

당일 회상은 session_search(ADR-041)가 이미 커버. 추가 LLM 상주 비용 대비
이득이 검증 안 됨 — Morpheus 야간 배치가 테제("판단은 배치 가능하다")의
검증된 형태. 재고 조건: 사용자가 당일 vault-회상 실패를 실제로 겪을 때.

### 기각 F — Mermaid 심볼 그래프 컨텍스트 오프로딩

코딩 에이전트의 장기 태스크용. birkin 게이트웨이는 채팅 표면 + 토큰
다이어트가 실측 기반으로 이미 해결.
