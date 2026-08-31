# Intent vs Reality

| intent_id | expected truth | observed reality | diff | violated invariant | intent source | observations | status | claims |
|---|---|---|---|---|---|---|---|---|
| ET-1 | delete-now는 독립 근거로 도달 불가가 증명된다 | 초기 탐색은 고신뢰 0 LOC를 보고 | 직접 AST·registration 검증 미완료 | 없음/unknown | 사용자 요청 | O-001 | unknown | C-001 |
| ET-2 | 대형 모듈은 삭제량과 이동량이 분리된다 | 초기 탐색은 250–690 delete, 4,000–4,950 move 가설 | 직접 중복·caller 검증 미완료 | 없음/unknown | 사용자 요청 | O-002 | unknown | C-002 |
| ET-3 | legacy는 소비자·일몰 조건으로 분류된다 | 초기 탐색은 7개 deferred 그룹과 3개 retain 그룹 보고 | Git ancestry와 외부 계약 검증 미완료 | 없음/unknown | 사용자 요청 | O-003 | unknown | C-003 |
| ET-4 | 합계는 중복 없이 신뢰도별 분리된다 | 아직 합계 전 | 검증·토론 필요 | 없음/unknown | 사용자 요청 | O-001,O-002,O-003 | unknown | C-004 |

## Update — 2026-08-31T10:00:00+09:00

| intent_id | expected truth | observed reality | diff | violated invariant | intent source | observations | status | claims |
|---|---|---|---|---|---|---|---|---|
| ET-1 | delete-now는 독립 근거로 도달 불가가 증명된다 | 354 LOC high-confidence, 83-101 LOC medium-confidence 후보를 직접 검증 | 초기 0 LOC 가설 반박 | 초기 lane이 alias/dynamic false positives를 피하는 과정에서 실제 orphan history를 충분히 추적하지 못함 | 사용자 요청 | O-005,O-006,O-007 | true | C-001A,C-001B |
| ET-2 | 대형 모듈은 삭제량과 이동량이 분리된다 | 추가 삭제 0 LOC, 250 상한 적용 최소 이동 18,172 LOC, 중복 review pool 198 LOC | 초기 250-690/4,000-4,950 가설 반박 | 초기 수치가 candidate ledger와 threshold arithmetic 없이 산출됨 | 사용자 요청 | O-008,O-009 | true | C-002A,C-002B |
| ET-3 | legacy는 소비자·일몰 조건으로 분류된다 | near-term 8개/486-506 LOC, profile 214 LOC, retain/product boundary 3개 | 초기 정확히 7개 그룹 가설 반박 | grouping policy와 persisted-data cutoff가 명시되지 않았음 | 사용자 요청 | O-010,O-011 | true | C-003A,C-003B,C-003C |

## EXPAND correction — 2026-08-31T10:50:00+09:00

| intent_id | expected truth | observed reality | diff | violated invariant | intent source | observations | status | claims |
|---|---|---|---|---|---|---|---|---|
| ET-1 | delete-now는 tracked+untracked 전체 소비자 부재로 증명된다 | high-confidence 165 LOC, conditional 18 LOC; OMO RPC/diagnostics는 명시적 API·feature retirement 필요 | 이전 354 LOC claim 축소 | `git grep`가 untracked 계약 테스트를 제외함 | 사용자 요청 | O-012 | true | C-001D,C-001E |

## Final convergence — 2026-08-31T12:10:00+09:00

| intent_id | expected truth | observed reality | diff | violated invariant | intent source | observations | status | claims |
|---|---|---|---|---|---|---|---|---|
| ET-1 | tracked+untracked 전체에서 후보가 수렴한다 | D-011 3 LOC 추가 후 final pass 신규 0; high-confidence 168 LOC | 없음 | 없음 | 사용자 요청 | O-013,O-014 | true | C-001F |
| ET-4 | 합계가 신뢰도와 조건별로 중복 없이 분리된다 | immediate 168-186; cumulative near-term 654-692; profile 868-906; movement 18,172 separate | 없음 | 없음 | 사용자 요청 | O-008,O-009,O-010,O-012,O-013 | true | C-001E,C-001F,C-002A,C-002B,C-003A,C-003B |
