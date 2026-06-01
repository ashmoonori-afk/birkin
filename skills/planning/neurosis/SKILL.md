---
name: neurosis
description: "Socratic deep-interview with mathematical ambiguity gating — turn a vague idea into a crystal-clear spec before acting."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [planning, requirements, interview, socratic, spec]
    source: "ported & adapted from gajae-code (Yeachan-Heo/gajae-code) deep-interview, which forked the Ouroboros idea"
---

# Neurosis — deep interview

Replace a vague idea with a crystal-clear specification by asking ONE targeted
question at a time, exposing hidden assumptions, scoring clarity mathematically,
and refusing to act until ambiguity drops below a threshold. Then write a spec
and stop for explicit approval. The obsessive-clarity counterpart to a quick
answer: birkin keeps interviewing until it genuinely understands.

**Conversation in Korean (한국어로 질문·진행 표시), the final spec in English** (birkin
house rule: 대화는 한국어, 산출물은 영어). One question per chat turn — the user
answers in their next message; works in the REPL and over Telegram alike.

## When to Use

- The user has a vague idea and wants it nailed down before birkin acts.
- They say "딥 인터뷰", "deep interview", "물어봐", "ask me everything", "don't
  assume", "확실히 이해하고", "neurosis", "ouroboros", "socratic".
- The task is complex enough that jumping to action would waste effort on the
  wrong thing ("그게 아니었는데" outcomes).

## When NOT to Use

- The request is already specific (clear goal, constraints, acceptance) — just do it.
- The user wants to brainstorm options — use the `brainstorming` skill.
- A quick one-off change — just do it.
- The user says "그냥 해" / "skip the questions" — respect it: stop, write a
  `pending approval` spec from what's known, do NOT act.

## Run parameters (provided by `birkin neurosis` / `/neurosis`)

The launcher passes: `idea`, `threshold` (+ source), `resolution`
(quick/standard/deep), `state_path`, `spec_path`. If you were given a
`state_path` that already has rounds, this is a RESUME — read it and continue.
Default threshold `0.05`; resolution presets: quick `0.6`, standard `0.5`,
deep `0.35` (lower = stricter).

## Procedure

### Phase 0 — announce the threshold (blocking)

Emit this as the very first line (substitute the resolved values):

```
딥 인터뷰 임계값: {threshold_percent} (source: {threshold_source})
```

### Phase 1 — initialize

1. Parse the idea. Detect **greenfield vs brownfield**: if the idea references an
   existing project/codebase/asset, use a read-only `spawn_subagent`/`explore` to
   gather facts FIRST (never ask the user what you can discover yourself); store as
   `codebase_context`. Cite the evidence (file/path/pattern) in any confirmation question.
2. If the initial idea/context is oversized, summarize it to a prompt-safe
   `initial_idea` first; carry the summary forward, not the raw dump.
3. Seed/refresh interview state at `state_path` (use the file tools):
   `{interview_id, type, initial_idea, rounds:[], current_ambiguity:1.0,
   threshold, threshold_source, codebase_context, topology:{...}, ontology_snapshots:[]}`.
4. Announce (Korean): the idea, project type, and "100%부터 시작, 임계값 이하가
   되면 진행" — one short paragraph.

### Round 0 — topology gate (once, before any scoring)

Lock the SHAPE before depth. Enumerate 1–6 top-level components that can succeed
or fail independently, then ask ONE confirmation question:

```
Round 0 | 구성요소 확인 | 모호도: 아직 점수 없음

이렇게 {N}개 최상위 구성요소로 이해했어요:
1. {이름}: {한 줄 설명}
2. ...

이 구성이 맞나요? 추가/삭제/병합/분리하거나, 보류할 게 있을까요?
```

Lock the confirmed components (id, name, description, status active|deferred,
evidence) into state. Single component → pass through. Detailed-but-one component
must NOT stand in for under-described siblings.

### Phase 2 — interview loop (repeat until `ambiguity ≤ threshold` or early exit)

**2a. Pick the target.** Identify the active component + dimension with the
LOWEST clarity. When >1 active components are similarly weak, rotate across them
(update `last_targeted_component_id`) so depth on one can't hide ambiguity in siblings.

**2b. Ask ONE question** (never batch). Questions expose ASSUMPTIONS, not feature
lists. State in one line why this dimension is the current bottleneck. Format:

```
Round {n} | 구성요소: {component} | 겨냥: {weakest_dimension} | 이유: {한 줄} | 모호도: {score}%

{질문}
```

Offer 2–4 contextual choices plus free-text where natural. Dimensions & styles:

| 차원 | 질문 스타일 | 예 |
|---|---|---|
| Goal | "정확히 무슨 일이 일어나죠?" | "'관리한다'고 할 때 사용자가 처음 하는 동작은?" |
| Constraints | "경계는?" | "오프라인에서도 동작해야 하나요, 인터넷 전제인가요?" |
| Success | "어떻게 됐을 때 성공인가요?" | "완성품을 보면 '바로 이거야' 하게 만드는 건?" |
| Context (brownfield) | "기존과 어떻게 맞물리죠?" | "`src/auth/`의 JWT 미들웨어를 확장할까요, 분리할까요?" |
| Ontology(범위가 흐릴 때) | "이게 본질적으로 뭐죠?" | "Task·Project·Workspace 중 핵심 엔티티는 무엇이고 나머지는 보조/뷰인가요?" |

**2c. Score after the answer** (be consistent; low temperature mindset). For each
active component score each dimension 0.0–1.0 (Goal, Constraints, Success, +Context
for brownfield) with a one-line justification + the remaining gap. Overall =
coverage-weighted weakest across active components. Then:

```
Greenfield: ambiguity = 1 − (goal×0.40 + constraints×0.30 + criteria×0.30)
Brownfield: ambiguity = 1 − (goal×0.35 + constraints×0.25 + criteria×0.25 + context×0.15)
```

**Ontology:** list key entities (noun, type, fields, relationships). Round 1 →
stability N/A. Rounds 2+: `stability_ratio = (stable+changed)/total` (renamed =
same type & >50% field overlap counts as *changed*, i.e. convergence). REUSE prior
entity names for the same concept; only rename for genuinely new concepts.

**2d. Report progress** — a compact table (차원/점수/가중치/가중값/gap), a Topology
line (targeted / active / deferred), an Ontology line (entity count / stability),
and the next target + why. Show the work.

**2e. Update state** at `state_path` (rounds, scores, per-component clarity,
ontology snapshot, last_targeted_component_id).

**2f. Soft limits.** Round 3+: honor early exit ("그만", "됐어", "이대로 가자") with a
warning showing remaining gaps. Round 10: soft warning. Round 20: hard cap, proceed
with current clarity. If ambiguity stalls (±0.05 for 3 rounds) → Ontologist mode.

### Phase 3 — challenge modes (each once, then resume normal questioning; track in state)

- **Round 4+ Contrarian:** challenge a core assumption — "반대라면? 이 제약이 사실은
  없다면?" Test whether the framing is real or habitual.
- **Round 6+ Simplifier:** "가치를 유지하는 가장 단순한 버전은? 어떤 제약이 진짜 필요한가?"
- **Round 8+ Ontologist (if ambiguity > 0.3):** "이게 정말 뭐죠? 추적된 엔티티 중
  핵심은?" Find the essence by examining the ontology.

### Phase 4 — crystallize the spec (when `ambiguity ≤ threshold`, early exit, or hard cap)

Write the spec **in English** to `spec_path` (`~/.birkin/specs/neurosis-{slug}.md`),
marked `pending approval`. Structure: Metadata (id, rounds, final ambiguity, type,
threshold+source, status PASSED|EARLY_EXIT) · Clarity breakdown table · Topology
(every confirmed component: covered or user-confirmed deferral) · Goal ·
Constraints · Non-Goals · Acceptance Criteria (testable checkboxes) · Assumptions
Exposed & Resolved · Technical Context · Ontology table · Ontology Convergence
table · collapsed full transcript.

### Phase 5 — approval bridge (birkin-ized; NO side effects until approved)

Until the user explicitly picks an execution option, do NOT mutate files, run
consequential shell, commit, or delegate. Present (Korean) via a clear question:

> spec 준비됨 (모호도 {score}%). 어떻게 진행할까요?

1. **birkin이 지금 실행** — 승인 시 birkin이 spec대로 작업 수행(필요하면 `spawn_subagent`로
   분할). 가장 빠름.
2. **메모리에 저장 + Morpheus에 위임** — spec을 vault 메모리 노트로 남겨 야간 Morpheus와
   향후 대화가 활용. (`remember`/`memory_write_note` 또는 `mcp__birkin__memory_write_note`)
3. **더 다듬기** — Phase 2로 돌아가 질문 계속.
4. **여기서 멈춤** — spec만 `pending approval`로 남김.

On approval of (1), proceed to execute. On (2), persist the spec summary to memory.
If oversized context was summarized, pass the spec + summary forward, never the raw dump.

## Output

- `~/.birkin/specs/neurosis-{slug}.md` — the crystallized spec (English), pending approval.
- Interview state at `state_path` (resumable).
- Optionally a memory note (when the user picks the memory/Morpheus option).

## Notes

- Gather codebase/context facts via a read-only subagent BEFORE asking the user.
- Keep prompts budgeted: summarize oversized transcripts before scoring/spec.
- This skill is a REQUIREMENTS pass, not an execution pass — clarity first, action
  only after explicit approval.
