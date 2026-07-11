# Ranking v2 기획 — BM25의 측정된 약점을 넘어서기

2026-07-11. 전제: Mnemosyne의 테제(산술 우선, 판단은 오프라인 배치, 질의 시 모델 0,
greppable)를 유지한다. "임베딩을 쓰면 된다"는 이미 측정했고(§5.1: RRF k=20이
+0.02 MRR) 그건 답이 아니라 비교선이다. **목표: 임베딩 없이 그 비교선을 잡는 것.**

## 1. 우리가 실제로 측정한 BM25의 약점

일반론이 아니라 이 저장소의 벤치마크가 보여준 것만 나열한다.

| # | 약점 | 측정 근거 |
|---|------|-----------|
| W1 | **Paraphrase 실명(失明)** — 질의가 노트와 다른 어휘를 쓰면 무너짐 | real-vault 동결 paraphrase 쿼리 R@5 **0.20** (LongMemEval 0.968과의 정직한 격차, 논문 §5.5) |
| W2 | **의미 신호의 잔여 마진** — 청크 dense와 융합하면 이김 | RRF k=20: +0.024 R@1 / +0.021 MRR (`dense-strong-20260711.json`) |
| W3 | **Cross-lingual 단절** — 한국어 노트 ↔ 영어 질의(또는 반대) 앵커 불일치 | 논문 §8이 명시한 "임베딩 re-ranker가 밥값 하는 유일한 케이스" |
| W4 | **Bag-of-words** — 구(phrase)·근접성·필드 구분 없음; 초안 near-duplicate 구별 불가 | real-vault: near-duplicate 초안들이 lexically-plausible 오답 다수 생성 (§5.5) |
| W5 | **시간 몰이해** — "지난달에 정리한", "예전 버전" 류 상대시간 질의 | 유형별 최저 밴드: single-session-preference 0.867, temporal-reasoning 0.953 (§5.1) |

## 2. 설계: 3계층 스택 "Anchor-Distilled BM25F" (ADB)

핵심 아이디어 한 줄: **의미 지식을 질의 시점의 벡터 연산이 아니라, 야간 큐레이션이
노트에 심어두는 어휘 앵커(텍스트)로 증류한다.** 검색은 끝까지 lexical — grep 가능,
diff 가능, 모델 0.

### L1 — BM25F + 근접성 (순수 산술, 즉시 구현 가능)

- **BM25F** [Robertson & Zaragoza 2004]: 단일 body 점수 대신 필드 가중 —
  `title > aliases/tags > headings > body`. near-duplicate 초안은 body가 겹쳐도
  title/heading이 다르므로 W4를 직접 공략. 역색인에 필드 태그만 추가하면 되고
  stdlib로 충분.
- **근접성 보너스** [Tao & Zhai 2007]: 질의어들이 한 윈도(예: 32토큰) 안에
  공기하면 가산. positional index 필요 → 인덱스 크기 증가가 유일한 비용.
  bag-of-words(W4)의 남은 절반.

### L2 — 오프라인 앵커 증류 (이 기획의 신규성, W1·W3의 정공법)

doc2query [Nogueira et al. 2019]와 SPLADE [Formal et al. 2021]가 보여준 사실:
검색 품질의 열쇠는 질의-문서 어휘 격차를 메우는 것이고, 그 확장은 **미리 계산해 둘
수 있다**. 그들은 모델·벡터로 저장하지만, 우리는 이미 야간에 LLM이 vault를 도는
구조(Morpheus)가 있으므로 **텍스트로 저장한다**:

- CurationPlan/1에 **`annotate` op 추가**: 큐레이터가 노트당
  `aliases:`(동의어·별칭), `queries:`(이 노트를 찾을 법한 질의 3-5개,
  paraphrase형), `xlang:`(한↔영 대역 키워드)를 **frontmatter에만** 기록.
- 안전 불변식은 그대로: `annotate`는 본문 불가침, frontmatter 화이트리스트 필드만,
  길이 상한(clamp), 삭제 불가 — 기존 executor 구조에 자연스럽게 들어감.
- 인덱스는 이 필드들을 BM25F의 고가중 필드로 흡수. **질의 시점에는 여전히 순수
  BM25F** — "판단은 배치 가능하다"는 논문 테제의 검색판.
- 부수 효과: 사용자가 앵커를 Obsidian에서 직접 읽고 고칠 수 있다(투명성 유지).

### L3 — 질의 시점 기계적 확장 (작고 보수적으로)

- **RM3-lite** [pseudo-relevance feedback, Abdul-Jaleel et al. 2004]: 1차 BM25F
  상위 k=3 문서에서 고-idf 용어 소수를 뽑아 저가중 재질의. 가드레일: 1차 결과
  최고점이 이미 높으면(명명 앵커 질의) 발동 안 함 — 명확한 질의를 흐리지 않는다.
- **시간 파서**(W5): 질의의 상대시간 표현("지난달", "최근", "예전") → 날짜 필터/
  부스트로 변환. 이미 랭킹에 든 decay 신호와 결합. 정규식 수준, stdlib.
- 링크 전파는 **이미 측정된 top-k=3 링크**(linkpolicy 실험)의 link-expansion을
  유지 — 새로 만들지 않음.

## 3. 평가 계획 (기존 하네스 재사용, 사전 등록)

| 지표 | 현재 BM25 | 목표 | 하네스 |
|---|---|---|---|
| LongMemEval MRR | 0.910 | **≥ 0.931** (임베딩 하이브리드 동률) | bench_longmemeval.py |
| real-vault R@5 (동결 40q) | 0.20 | **≥ 0.30** (W1 직접 측정) | bench_real_vault.py `--skip-curation` + 기존 vault |
| Korean/mixed | BM25 우위 유지 | 회귀 0 | bench_korean_embed.py |
| 간섭 그리드 | 명확한 격차 100% 불변 | 회귀 0 (L3가 near-tie 재배열 악화시키지 않는지) | bench_weight_sensitivity.py |

- **Ablation 필수**: L1 단독 → L1+L2 → L1+L2+L3 누적 + 각 층 단독. 어느 층이
  밥값을 하는지 분리 — 논문 §5.2와 같은 방식.
- real-vault 쿼리는 이미 동결돼 있으므로(realvault-queries.json) adaptive tuning
  오염 없음. L2 앵커 생성 프롬프트는 이 쿼리들을 절대 보지 않는다(오염 규칙).

## 4. 리스크와 정직한 한계

- **L2는 큐레이터 품질에 의존** — 안전은 executor가 보장하지만 앵커의 *품질*은
  §5.4처럼 엔진별 측정 대상. 나쁜 앵커는 정밀도를 해칠 수 있음 → aliases 필드
  가중치를 sweep하고, 앵커 없는 조건과 항상 비교.
- **RM3 drift** — 개인 vault의 near-duplicate가 확장을 오염시킬 수 있음.
  가드레일(고신뢰 1차 결과 시 미발동)이 핵심이고, ablation에서 단독 측정.
- **인덱스 크기** — positional index로 수 배 증가 예상. 1,910노트 실측 후 판단
  (현재 인덱스 45KB 수준이라 여유 큼).
- W2(의미 마진)를 100% 잡는다는 보장은 없다 — 목표 미달 시 논문처럼 정직하게
  "격차 X 남음"으로 보고하고, 하이브리드는 옵션으로 남긴다.

## 5. 실행 순서 (작은 것부터, 각 단계 벤치 게이트)

1. **L1 BM25F+근접성** — mnemosyne.py 인덱스/스코어러 확장 + 단위 테스트 (~반나절)
2. **L3 시간 파서** — 독립적이고 작음 (~2시간)
3. **L2 annotate op** — curation.py op 추가 + executor clamp + 프롬프트 (~1일)
4. **전체 ablation 벤치** → 결과가 목표를 넘으면 논문 §5.1 후속(v3) 또는 별도 노트

## 6. 실험 결과 (2026-07-11 실행 — 계획 대비 실측)

**최종: lexical-only가 임베딩 하이브리드를 넘었다.** 동결 구성
(`BM25F w_user=3, k1=0.9, b=0.5` + **질의어 가중 = idf¹** + temporal window
prior λ=0.3), full 470문항:

| | R@1 | R@5 | MRR |
|---|---|---|---|
| BM25 기준 | 0.870 | 0.968 | 0.910 |
| **FINAL (lexical-only)** | **0.900** | **0.977** | **0.933** |
| 임베딩 하이브리드 (rrf_k20, best-of-3k) | 0.894 | 0.977 | 0.931 |

라운드 로그 (dev 235 / test 235 분할, dev에서만 튜닝):

| 라운드 | 시도 | 결과 | 판정 |
|---|---|---|---|
| 1 | bm25f/prox/rm3/fuse | bm25f +0.004 MRR; prox·rm3 해로움 | bm25f만 채택 |
| 2 | lexical chunk max-pool (dense를 살린 처방) | 0.851 R@1 — 역효과 | 기각 |
| 3 | K1·B·w_user 64-그리드 + 오답 매니페스트 | k1=0.9 b=0.5 w=3 → dev 0.885/0.926 | 채택 |
| 4 | **질의어 idf 가중**(오답 분석: 잡담 노이즈 억제) + tie-break + time | **idf¹+time0.3 → dev 0.915/0.943**; tie-break 해로움 | idf·time 채택 (idf는 p=1 정점의 역U자) |
| 5 | 워드 바이그램 구 필드 | dev 단조 악화 | 기각 (test 미사용) |

**정직성 사항** — 논문 §5.4와 같은 기준으로 기록:
- 미접촉 test 절반(1회 평가): FINAL 0.885/0.979/0.923 — 하이브리드의
  full-set 수치 대비 R@1 −0.009 / MRR −0.008, R@5 +0.002. dev 이득의 절반은
  dev 특화였다. full-대-full 비교가 성립하는 근거: 하이브리드의 k도 full에서
  3개 중 사후 선택된 값(우리 쪽 노출이 오히려 적음 — dev 절반만 사용).
- test 스플릿 평가 횟수: 2회 (라운드 4에서 스크립트 결함으로 비최종 조건들이
  함께 노출됨 — 구성 선택에 사용하지 않았음을 명시).
- 마진은 작다 (R@1 +0.006 ≈ 3문항). 하이브리드의 문항별 순위가 없어 짝지은
  부트스트랩 CI는 불가 — "동급 이상"이 방어 가능한 표현이고 "확실히 우월"은
  아니다.
- L2(앵커 증류)는 이 벤치마크에선 불필요했다. real-vault paraphrase 격차(R@5
  0.20)에는 여전히 L2가 정공법 — 후속 과제.

**채택 구성의 해석** (전부 산술, 임베딩·모델 0):
질의어를 idf로 가중하면 희귀 앵커("thermostat")가 잡담 토큰("I've been
thinking")을 지배한다 — BM25의 idf가 문서 매칭에는 적용되지만 질의 토큰 간
상대 가중에는 없던 축. 여기에 사용자 발화 필드 가중(개인 기억의 사전확률),
컬렉션 튜닝된 K1/B, 그리고 상대시간 질의의 날짜 윈도 사전확률이 얹힌다.

후속 (미착수): mnemosyne.py 프로덕션 랭킹에 idf 가중·시간 사전확률 이식 +
한국어 벤치·간섭 그리드 회귀 확인; real-vault에서 L2 앵커 증류 실험.

## 참고 문헌

- Robertson & Zaragoza, "Simple BM25 extension to multiple weighted fields" (BM25F), CIKM 2004
- Tao & Zhai, "An exploration of proximity measures in information retrieval", SIGIR 2007
- Abdul-Jaleel et al., "UMass at TREC 2004" (RM3), TREC 2004
- Nogueira et al., "Document expansion by query prediction" (doc2query), arXiv:1904.08375
- Formal et al., "SPLADE: sparse lexical and expansion model", SIGIR 2021 — L2는 이것의 stdlib·텍스트판
