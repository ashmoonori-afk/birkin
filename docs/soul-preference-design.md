# SOUL / PREFERENCE 역할 파일 — 현황 실측과 설계안

작성: 2026-08-20 · 브랜치 `design/memory-role-files-20260820`
상태: **설계 확정(미구현)** — 열린 분기 D1/D2/D3 결정 완료(§7), 선행 조건 3건 미해소

목적: birkin이 "말투(soul)"와 "사용자 선호(preference)"를 실제로 제대로 구현하고
있는지 코드로 확인하고, 안 되는 부분의 원인을 규명한 뒤, hermes-agent와 omo native의
방식을 근거로 birkin용 설계를 제안한다.

---

## 1. 결론 요약

| 항목 | 현황 | 판정 |
|---|---|---|
| **SOUL (말투/정체성)** | `~/.birkin/SOUL.md`가 시스템 프롬프트 슬롯 #1을 대체. REPL은 매 턴 새로 읽음 | **구현됨** (결함 3건) |
| **PREFERENCE (선호)** | 전용 파일 없음. vault 노트의 `type=preference`가 `identity` 존에 들어가고, **요약 한 줄만** 프롬프트에 노출 | **부분 구현 — 역할 파일 아님** |
| **자동 저장(백그라운드 리뷰)** | 없음. 모델에게 "저장해보라"고 권하는 **넛지 문자열**이 전부 | **미구현** |
| **mnemosyne `ProfileMemory`** (user/preferences/soul/workflow/automation 5종) | 별도 저장소에 구현·커밋(`0305da5`)되어 있으나 birkin은 이를 **의존하지도, 포팅하지도 않음** | **미연결** |

한 줄 요약: **soul은 되고 preference는 "노트 타입"으로만 흉내 내는 상태**이며,
설계상 5종 역할 파일은 birkin 코드베이스에 존재하지 않는다.

---

## 2. 실측 증거 (코드 + 실행)

### 2.1 SOUL — 구현되어 있다

- `birkin/persona.py` — `soul_path() = config.birkin_home()/"SOUL.md"`,
  `read_soul()` / `write_soul()`(temp+atomic replace) / `seed_default()`,
  프리셋 `warm|concise|mentor|direct`.
- `birkin/promptgate.py:154` — `_persona()`: `persona_text is None`이면 **매 호출마다
  `read_soul()`로 새로 읽음**, `""`이면 페르소나 없음.
- `birkin/prompts.py:118` — `identity = persona.strip() if persona ... else _IDENTITY`.
  즉 SOUL.md는 기본 정체성 문단을 **치환**한다(hermes의 슬롯 #1과 동일 개념).
- `birkin/slashcommands.py:837` — `/persona [warm|concise|mentor|direct|path|reset]`
  (별칭 `/soul`).
- 실행 확인: SOUL.md가 없으면 `read_soul() == ""` → 기본 정체성 문단이 사용됨.

**결함 S1 — 웜 게이트웨이 세션에서 즉시 반영 안 됨.** 영구 게이트웨이는 세션 시작 시
시스템 프롬프트를 스냅샷하므로 `/persona` 변경은 `/new` 전까지 무효
(`birkin/persona.py` 모듈 독스트링에 명시된 알려진 동작). 사용자 입장에서는 "바꿨는데
그대로"로 보인다.

**결함 S2 — 신뢰 등급이 낮은 채널에서 페르소나가 통째로 사라짐.**
`birkin/runtime.py:127,185` — `persona_text=None if trusted else ""`.
보안상 타당하지만, 텔레그램 등에서 birkin의 목소리가 조용히 기본값으로 바뀐다는
사실이 사용자에게 고지되지 않는다.

**결함 S3 — SOUL.md 이름 충돌.** `birkin/prompts.py:16`의
`_WORKSPACE_PROMPT_FILES = ("SOUL.md", "AGENTS.md", "TOOLS.md")`는 **작업 디렉터리의**
`SOUL.md`를 별도 섹션으로 덧붙인다. `~/.birkin/SOUL.md`(정체성 슬롯)와 경로만 다른
동명 파일이 서로 다른 슬롯에 주입되어, 둘 다 있으면 목소리가 이중으로 정의된다.

### 2.2 PREFERENCE — 역할 파일이 아니다

- `birkin/memory.py:49` — `VALID_TYPES = {"person","project","preference","fact","topic","session"}`.
- `birkin/mnemosyne.py:74` — `TYPE_ZONE`에서 `"preference": "identity"`.
  `IDENTITY_ZONE`은 `mnemosyne.py:714`에서 아카이브 대상에서 제외된다(감쇠 안 함 — 좋음).
- `birkin/memory.py:624` — `remember(key, value)`는 `"Profile - <key>"` 제목의
  **노트 1건**을 `type=preference`로 쓴다.
- `birkin/memory.py:573` `render()` → `runtime.py:124,181,413`에서
  `memory_block`으로 전달 → `prompts.py:141` `"## What you know about the user"`.

실행 확인 1 — 선호는 **요약 한 줄**로만 들어간다:

```
## What you know about the user
Vault: ...\vault (3 notes). Use memory_search / memory_get_note for details.
[identity]
- [[Profile - language]] (preference): language: Korean replies
- [[Profile - tone]] (preference): tone: concise, no filler
[projects]
- [[Birkin project]] (project): Birkin is a CLI agent workspace.
```

**결함 P1 — 조용한 유실.** `birkin/memory.py:607`은 identity 존을 `cap = min(left, 5)`로
자른다. 선호 8건 + 사실 10건을 쓰고 `render()`를 호출한 실측 결과: **선호 8건 중 5건만
노출, 나머지 3건은 잘렸다는 표시조차 없이 사라짐**. 총 예산도 `limit=10` 항목 고정이라
노트가 늘수록 선호가 밀려난다. (hermes는 반대로 한도 초과 시 **에러를 던져** 에이전트가
직접 통합/삭제하게 만든다.)

**결함 P2 — 본문이 아니라 포인터.** 프롬프트에는 요약 한 줄만 있고 본문은
`memory_get_note` 호출이 필요하다. "짧은 답을 선호" 같은 규칙은 **읽어야 지켜지는데**,
모델이 도구를 호출하지 않으면 적용되지 않는다.

**결함 P3 — 키당 노트 1개.** `Profile - tone`, `Profile - language`처럼 선호마다 별도
파일이 생겨 identity 존 5칸을 서로 잠식한다. 통합(consolidation) 경로가 없다.

**결함 P4 — 저장이 확률적.** 자동 저장은 `birkin/agent.py:38`의 `_MEMORY_NUDGE`
("…durable fact를 배웠으면 remember로 저장해라…")를 다음 턴에 끼워 넣는 것이 전부다
(`agent.py:596` `_update_nudges`). 모델이 무시하면 아무것도 저장되지 않는다.
**대화를 사후 검토하는 백그라운드 리뷰는 birkin에 없다.**

### 2.3 왜 안 되는가 (근본 원인)

1. **역할 파일 계층 자체가 없다.** birkin의 always-in-context 자산은
   `SOUL.md`(정체성) + `AGENTS.md/TOOLS.md`(작업공간) + `render()` 인덱스뿐이다.
   "사용자 프로필"에 해당하는 **에이전트 소유 파일**이 없어서 선호가 일반 노트 검색
   공간으로 떨어진다.
2. **설계는 다른 저장소에 있고 연결되지 않았다.**
   `mnemosyne/birkin_mnemosyne/profiles.py`의 `ProfileMemory`는 정확히 그 계층
   (`system/{user,preferences,soul,workflow,automation}.md`, 백그라운드 리뷰,
   JSON 계약, 원자적 쓰기, vault 락)을 구현했지만, `birkin/pyproject.toml`의
   의존성은 `psutil`, `typing-extensions`뿐이고 `git ls-files birkin`에 `profiles.py`가
   없다. birkin은 mnemosyne 코드를 **벤더링 복사**해 쓰는 구조라
   (`birkin/mnemosyne.py`, `birkin/curation*.py`), profiles만 복사되지 않은 채 남았다.
3. **예산 정책이 "자르기"다.** hermes/omo는 "한도 초과 → 에이전트가 정리"인데,
   birkin은 "한도 초과 → 조용히 렌더에서 제외"다. 사용자 눈에는 망각으로 보인다.
4. **쓰기 트리거가 프롬프트 힌트뿐이다.** 캡처 보장이 없다.

---

## 3. 참고 구현 — hermes-agent

출처: [Persistent Memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/),
[Which File Does What?](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/which-file-does-what.md)

- **소유권 분리가 핵심.** `SOUL.md`는 **사람**이 쓰는 정체성(슬롯 #1),
  `USER.md`는 **에이전트**가 `memory` 도구로 쓰는 사용자 프로필, `MEMORY.md`는
  에이전트가 배운 환경/관례. 문서가 명시적으로 경고한다 — "SOUL.md를 편집해도
  USER.md는 채워지지 않고, memory 항목은 페르소나를 바꾸지 않는다."
- **작고 고정된 예산.** `MEMORY.md` 2,200자(~800토큰), `USER.md` 1,375자(~500토큰).
  프롬프트 헤더에 `[67% — 1,474/2,200 chars]`처럼 사용률을 노출해 에이전트가
  자기 용량을 인지한다. 항목 구분자는 `§`.
- **본문 그대로 주입.** 요약/포인터가 아니라 항목 전체가 시스템 프롬프트에 들어간다.
  `read` 액션이 아예 없다 — 이미 컨텍스트에 있기 때문.
- **한도 초과 = 에러.** 자동 압축을 하지 않고 현재 항목 목록과 함께 에러를 반환해
  같은 턴에서 통합(`replace`)/삭제(`remove`) 후 재시도하게 만든다.
- **동결 스냅샷.** 세션 시작 시 1회 주입, 세션 중 변경은 디스크에만 반영(프리픽스 캐시
  보존). 도구 응답은 항상 라이브 상태를 보여준다.
- **캡처 보장 = 백그라운드 리뷰.** 턴 종료 후 자기개선 리뷰 포크가 대화를 검토해
  메모리/스킬을 갱신한다. 저가 모델로 돌릴 수 있고(`auxiliary.background_review`),
  끌 수도 있다.
- **동의 게이트.** `memory.write_approval: true`면 모든 쓰기(특히 백그라운드 쓰기)가
  `/memory pending → approve/reject`로 스테이징된다. 알림 강도는
  `display.memory_notifications: off|on|verbose`.
- **쓰기 시 보안 스캔.** 프롬프트 인젝션/자격증명 유출 패턴, 비가시 유니코드 차단.

## 4. 참고 구현 — omo native

출처(로컬 설치본): `omo-ai/plugin/extensions/reflection-persona.md`,
`facts-persona.md`, `memory-run-supervisor.mjs`, `omo-memory-mcp.js`.

- **3계층 메모리 파일시스템**(git 저장소 `$MEMORY_DIR`):
  - `system/` — **항상 컨텍스트에 있는 프롬프트**. 정체성/선호/관례/활성 프로젝트만.
  - `skills/` — 절차적 기억. 재사용 가능한 다단계 워크플로만.
  - 그 외 전부 — **외부 기억**. 트리와 `description`만 보이고 본문은 필요할 때 조회.
- **투영(projection)**: `system/persona.md`(자기 모델), `system/human.md`(사용자)가
  다음 실행의 시스템 프롬프트에 XML로 주입되고, 비-system 경로는 **이름만** 트리로
  노출된다. 커밋된 내용만 반영된다(= 감사 가능한 메모리).
- **백그라운드 reflection 서브에이전트**가 대화 종료 후 5단계로 동작:
  조사 → 추출(실수·교정 > 선호·패턴 > 사실 > 모순 > 재사용 절차) → 갱신 → 검토 → 커밋.
  필터가 명시적이다 — 지속성/기존 포함 여부/일반화 가능성/상대 날짜 절대화/메모리 vs 스킬.
- **정체성 파일 보호 규칙**: "persona and behavioral files are load-bearing. Edit them
  surgically: append, modify specific entries… **Never rewrite them wholesale**."
- **모순은 원본에서 수정**(새 항목을 옆에 덧붙이지 않음), 은퇴 컨텍스트는 `ARCHIVE.md`로.
- **사실 추출은 별도 저가 페르소나**(`facts-persona.md`)가 JSONL 계약으로 처리 —
  스키마가 두 줄로 고정되어 있어 검증이 쉽다.

### 두 구현의 공통 교훈 (birkin에 부족한 것)

1. 사람 소유 파일과 에이전트 소유 파일을 **절대 섞지 않는다**.
2. always-in-context 슬롯은 **작고 고정된 예산 + 사용률 가시화 + 본문 그대로**.
3. 한도 초과는 **에러/통합**이지 조용한 절단이 아니다.
4. 캡처는 프롬프트 힌트가 아니라 **대화 후 백그라운드 리뷰**로 보장한다.
5. 자동 쓰기에는 **승인 게이트와 알림**이 따라붙는다.

---

## 5. 설계안 — birkin Role Files v1

### 5.1 계층 (소유권을 파일 경로로 고정)

```
~/.birkin/
  SOUL.md                 # 사람 소유. 정체성 슬롯 #1. 현행 유지.
  profile/                # 에이전트 소유. 항상 컨텍스트.
    user.md               # 사용자 특성 (이름/역할/환경)
    preferences.md        # 선호 (형식/언어/금지사항)
    mask.md              # 관찰된 대화 스타일  ← mnemosyne의 soul.md 대응
    workflow.md           # 작업 진행 방식
    automation.md         # 자동화 지침
  memory/                 # 현행 vault. 인덱스/검색 계층(변경 없음).
```

핵심 결정: **mnemosyne의 `system/soul.md`를 그대로 옮기지 않고 `profile/mask.md`로
이름을 바꾼다.** 이유 — birkin에는 이미 사람이 소유한 `SOUL.md`가 있고, hermes 문서가
경고하는 "두 개의 목소리 파일" 혼동을 그대로 수입하게 된다. `mask.md`는 에이전트가
관찰한 스타일 요청만 담고 SOUL.md **다음** 슬롯에 주입하며, `/persona promote`로
사용자가 승인 시 SOUL.md에 병합한다.

> **결정 D1(2026-08-20, 확정): 분리.** mnemosyne의 `system/soul.md`는 birkin에서
> `profile/mask.md`로 이름을 바꿔 이식한다. `SOUL.md`(사람 소유)와
> `profile/mask.md`(에이전트 소유)의 경계는 hermes의 SOUL/USER 분리와 동일하며,
> 승격은 `/persona promote`로만 일어난다(에이전트는 `SOUL.md`를 쓰지 않는다).
> mnemosyne 쪽 파일명은 그대로 두고, birkin의 어댑터에서 `soul → mask`로 매핑한다.

### 5.2 주입 (프롬프트 계약)

- 순서: `SOUL.md`(정체성 치환) → `profile/mask.md` → `profile/user.md` →
  `profile/preferences.md` → `profile/workflow.md` → `profile/automation.md` →
  기존 `## What you know about the user`(vault 인덱스) → 작업공간 파일.
- 역할 파일은 **본문 그대로**, 항목 구분자는 개행 `- ` 리스트(mnemosyne `## Guidance`
  포맷과 호환).
- 각 블록 헤더에 사용률 표기: `### Preferences [42% — 578/1375 chars]`.
- 예산(설정 가능, 기본값): `user 1,375` / `preferences 1,375` / `mask 800` /
  `workflow 1,000` / `automation 800`자. 합계 ≈ 5.3KB(~1.9K 토큰).
- 빈 파일은 블록 자체를 생략(토큰 낭비 방지).

### 5.3 쓰기 경로

1. **전경(도구)**: `remember(key, value)` → 노트 대신 `profile/preferences.md`에
   추가/치환. `profile_write(target, action, old_text, content)` 도구를 신설하고
   hermes식 `add|replace|remove` + 부분 문자열 매칭을 채택.
2. **배경(리뷰)**: `birkin_mnemosyne.profiles.ProfileMemory`를 **의존성으로 가져다
   쓴다**(결정 D3, §5.10). 턴 종료 후 `record_exchange(user, assistant)`를 큐잉하고
   1-worker 스레드에서 JSON 계약(`{"profiles": {...}}`)으로 검토·기록. 실패는 대화에
   영향 없음. 리뷰 프롬프트는 omo `reflection-persona.md`의 필터(지속성/중복/일반화/
   절대날짜)를 압축해 사용.

   > **결정 D2(2026-08-20, 확정): 보조 모델.** 리뷰는 메인 대화 모델이 아니라
   > 별도 저가 모델로 돌린다(`profile.background_review.{provider,model}`).
   > 결과: 리뷰가 메인 모델의 프리픽스 캐시를 재사용할 수 없으므로 전체 트랜스크립트
   > 재생은 낭비다 — hermes와 동일하게 **다이제스트 재생**(최근 N턴 원문 + 이전 요약)을
   > `ProfileReviewer` 입력으로 넘긴다. `ProfileExchange(user, assistant)` 계약은
   > 그대로 두고, 다이제스트 구성은 birkin 쪽 어댑터 책임으로 한다.
   > 보조 모델 미설정 시에는 리뷰를 **끈다**(메인 모델로 조용히 폴백하지 않는다 —
   > 비용이 사용자 모르게 늘어나는 것을 막기 위함).
3. **한도 초과**: 조용히 자르지 않고 도구 에러 + 현재 항목 목록 반환 → 같은 턴에서
   통합 후 재시도(hermes 방식). **결함 P1 수정.**
4. **중복**: 동일 라인은 무시(mnemosyne 현행 동작 유지).
5. **모순**: 새 항목 추가 전 기존 항목과 충돌 검사 → `replace` 강제(omo 규칙).

### 5.4 갱신 시맨틱

- REPL: 매 턴 재읽기(`promptgate._persona`와 동일 경로에 `profile` 로더 추가).
  **결함 S1을 REPL에서는 발생하지 않게 유지.**
- 게이트웨이: 세션 시작 스냅샷(프리픽스 캐시 보존). 단, 프로필이 바뀌면
  `💾 profile updated — /new 이후 적용` 한 줄을 채널에 출력. **S1을 침묵에서 고지로 강등.**

### 5.5 보안/신뢰

- 주입: `trusted`가 아니면 역할 파일 블록도 주입하지 않는다(현행 persona/memory 정책과
  동일). 단 채널 첫 응답에 "이 채널에서는 프로필이 적용되지 않음"을 1회 고지 → **S2 수정.**
- 쓰기: 비신뢰 채널에서 온 발화는 **프로필을 갱신할 수 없다**(프롬프트 인젝션으로 인한
  프로필 오염 차단). 배경 리뷰도 동일 게이트를 통과해야 한다.
- 쓰기 전 스캔: 비가시 유니코드/인젝션·유출 패턴 차단(hermes 방식). 기존
  `birkin/promptgate.py`의 검사 자산 재사용.
- 승인 게이트: `profile.write_approval`(기본 `false`), `/profile pending|approve|reject`.

### 5.6 마이그레이션

- 1회 마이그레이션: vault의 `type=preference` 노트(=identity 존) 중 `Profile - *`를
  `profile/preferences.md` 라인으로 옮기고, 원본 노트는 `_archive` 존으로 이동.
  손실 없음(노트는 남고 검색 가능).
- `SOUL.md` 및 `/persona` 동작은 변경 없음(하위 호환).
- 작업공간 `SOUL.md`(S3)는 `_WORKSPACE_PROMPT_FILES`에서 제외하고
  `AGENTS.md`/`TOOLS.md`만 남긴다. 제거 시 릴리스 노트에 명시.

### 5.7 설정

```jsonc
"profile": {
  "enabled": true,
  "write_approval": false,
  "limits": { "user": 1375, "preferences": 1375, "mask": 800,
              "workflow": 1000, "automation": 800 },
  "background_review": {
    "enabled": true,
    "provider": null,        // 필수. 미설정이면 리뷰를 끈다(메인 모델 폴백 없음).
    "model": null,           // 예: 저가 flash급 모델
    "digest_recent_turns": 6 // 이전 턴은 요약으로 압축해 재생
  }
}
```

### 5.8 코드 조달 및 의존성 경계 (결정 D3)

> **결정 D3(2026-08-20, 확정): 의존성 추가.** `ProfileMemory`를 벤더링 복사하지 않고
> `birkin-mnemosyne` 패키지를 의존성으로 추가한다.

조사 결과 다음 선행 조건이 확인되었고, **구현 전에 모두 해소되어야 한다**:

| # | 사실 (실측) | 필요한 조치 |
|---|---|---|
| C1 | `birkin-mnemosyne`는 PyPI에 없음 (`/pypi/.../json` → 404). GitHub 저장소는 존재 (200) | PyPI 배포, 또는 git URL 의존성 사용 |
| C2 | `ProfileMemory`를 추가한 커밋 `0305da5`가 **origin에 push되지 않음** (`main...origin/main [ahead 1]`) | 먼저 push + 버전 태그(예: `v0.2.0`) |
| C3 | `profiles.py:11`이 `from typing import Self` 사용 — `typing.Self`는 **Python 3.11+**인데 두 패키지 모두 `requires-python = ">=3.10"` | mnemosyne 쪽에서 `typing_extensions.Self`로 교체(birkin은 이미 `typing-extensions>=4.12` 의존) 또는 `requires-python`을 3.11로 상향 |

C1은 git URL 의존성으로 해결 가능하다 — `birkin` 자체가 PyPI에 배포되지 않고
(`/pypi/birkin/json` → 404, publish 워크플로 없음) 소스 설치 방식이라,
PyPI가 금지하는 direct URL dependency 제약에 걸리지 않는다:

```toml
dependencies = [
  "psutil>=6",
  "typing-extensions>=4.12",
  "birkin-mnemosyne @ git+https://github.com/ashmoonori-afk/birkin-mnemosyne@v0.2.0",
]
```

**의존성 경계 (필수 제약).** birkin의 벤더링 `birkin/mnemosyne.py`(780줄)와 패키지의
`birkin_mnemosyne/mnemosyne.py`(676줄)는 이미 갈라져 있다 — `INDEX_VERSION` 3 vs 1,
`INDEX_FILE` `.birkin-index.json` vs `.mnemosyne-index.json`, birkin에만 있는
시간 사전확률(`TIME_PRIOR_LAMBDA`, `temporal_target`)과 `STRENGTH_STEP`.
**두 인덱스 구현이 한 프로세스에서 같은 vault를 만지면 인덱스가 깨진다.**

따라서 birkin이 import해도 되는 것은 `birkin_mnemosyne.profiles`뿐이다
(`profiles.py`의 외부 의존은 `atomic_write` 하나이며 두 구현에서 동일).
`birkin_mnemosyne.mnemosyne` / `Mnemosyne` / `curation*`은 **import 금지**이며,
이를 `tests/test_profile_import_boundary.py`로 강제한다(모듈 소스 정적 검사).

### 5.9 검증 계획 (구현 시 착수 순서)

1. `tests/test_profile_files.py` — bootstrap(5파일 생성 + frontmatter),
   한도 초과 시 **에러이며 기존 항목 무손실**, 중복 라인 무시, 동시 쓰기 락,
   `add/replace/remove` 부분 문자열 매칭, 잘못된 JSON 계약 거부.
2. `tests/test_profile_prompt.py` — 주입 순서/본문 그대로/사용률 헤더/빈 블록 생략,
   `trusted=False`에서 전체 생략.
3. `tests/test_profile_migration.py` — `Profile - *` 노트 → `preferences.md`,
   원본 아카이브, 재실행 멱등.
4. 회귀: `tests/test_persona.py`, `tests/test_memory_zones.py`,
   `tests/test_memory_transparency.py` 무변경 통과.
5. `tests/test_profile_import_boundary.py` — birkin 코드가 `birkin_mnemosyne.profiles`
   외의 심볼(특히 `Mnemosyne`, `curation*`)을 import하지 않음을 정적으로 검증(§5.8).
6. `tests/test_profile_review_model.py` — 보조 모델 미설정 시 리뷰가 **꺼지고**
   메인 모델로 폴백하지 않음, 다이제스트가 `digest_recent_turns`를 지킴,
   리뷰 실패가 대화 턴을 깨지 않음.
7. 수동: `/persona`, `/persona promote`, `/profile`, `--help`, 잘못된 인자 1건
   (AGENTS.md 커밋 게이트 준수).

### 5.10 비목표

- vault 검색/랭킹 알고리즘 변경 없음. 역할 파일은 **인덱스 위의 얇은 계층**이다.
- 외부 메모리 프로바이더 연동 없음.
- 역할 파일에 대한 시맨틱 검색 없음(항상 컨텍스트이므로 불필요).

---

## 6. 예상 효과 (실측 대비)

| 결함 | 현재 | 설계안 |
|---|---|---|
| P1 조용한 유실 | 선호 8건 중 5건만 노출, 경고 없음 | 한도 도달 시 에러 + 통합 유도, 유실 0 |
| P2 포인터 | 요약 한 줄, 본문은 도구 호출 필요 | 본문 그대로 주입 |
| P3 키당 노트 | identity 5칸 상호 잠식 | 파일 1개에 라인 누적, 예산은 문자 기준 |
| P4 확률적 저장 | 넛지 문자열뿐 | 턴 후 백그라운드 리뷰 + 승인 게이트 |
| S1 웜 세션 | 침묵 | `/new` 안내 한 줄 |
| S2 비신뢰 채널 | 침묵 | 1회 고지 + 쓰기 차단 |
| S3 이름 충돌 | SOUL.md 두 군데 | 작업공간 SOUL.md 제외 |

---

## 7. 결정 사항 (2026-08-20 확정)

| ID | 결정 | 반영 위치 |
|---|---|---|
| **D1** | **분리** — mnemosyne의 `soul.md`는 birkin에서 `profile/mask.md`로 이식. `SOUL.md`는 사람 소유로 유지하고 에이전트는 쓰지 않는다. 승격은 `/persona promote` | §5.1 |
| **D2** | **보조 모델** — 백그라운드 리뷰는 별도 저가 모델로 실행하고 다이제스트를 재생. 미설정 시 리뷰를 끈다(메인 모델 폴백 없음) | §5.3, §5.7 |
| **D3** | **의존성 추가** — `ProfileMemory`를 벤더링하지 않고 `birkin-mnemosyne`를 의존성으로 추가. import 경계는 `birkin_mnemosyne.profiles`로 한정 | §5.8 |

### 구현 착수 전 선행 조건 (D3에서 파생, 모두 미해소)

1. mnemosyne 커밋 `0305da5`를 origin에 push하고 버전 태그를 붙일 것 (현재 `ahead 1`).
2. `profiles.py`의 `from typing import Self`를 `typing_extensions.Self`로 교체하거나
   `requires-python`을 `>=3.11`로 올릴 것 — 현재 선언(`>=3.10`)에서는 3.10 설치가
   import 시점에 깨진다.
3. PyPI 배포 또는 git URL 의존성 중 하나를 확정할 것 (§5.8 C1 — 후자로 진행 가능).

## 8. 출처

- 코드: `birkin/{persona,promptgate,prompts,memory,mnemosyne,agent,runtime,slashcommands}.py`,
  `birkin/pyproject.toml`, `mnemosyne/birkin_mnemosyne/profiles.py`(커밋 `0305da5`).
- 실측: 임시 `BIRKIN_HOME` vault에 선호/사실 노트를 기록한 뒤 `VaultMemory.render()`와
  `prompts.build_system_prompt()` 출력을 직접 확인(§2.2).
- hermes-agent: <https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/>,
  <https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/which-file-does-what.md>
- omo native: 로컬 설치본 `omo-ai/plugin/extensions/reflection-persona.md`,
  `facts-persona.md`, `memory-run-supervisor.mjs`, `omo-memory-mcp.js`.
