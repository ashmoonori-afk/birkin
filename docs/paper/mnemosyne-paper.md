# Birkin-Mnemosyne: A Zero-Dependency Lexical Memory Palace with Safe, Provider-Portable Curation for Personal LLM Agents

*Birkin project · draft, 2026-07 · code, tests, and benchmark harness in the birkin repository.*

> **Naming note.** "Mnemosyne" is also the name of an unrelated concurrent
> system — Jonelagadda et al.'s human-inspired graph memory for edge LLMs
> [20]. To avoid confusion we title this work **Birkin-Mnemosyne** and refer to
> the retrieval subsystem as the Birkin memory engine; the two share only the
> mythological name, not architecture (graph store + LoCoMo there; stdlib BM25
> vault + a curation-safety interface here).

---

## Abstract

Memory for LLM agents increasingly means infrastructure — embedding models,
vector databases, graph servers, an LLM call on every write. We ask how much a
*personal* agent (one user, one machine, thousands of notes) actually needs, and
make two claims.

First, a transparent lexical substrate is enough for personal-scale retrieval
on the long-term-memory benchmark we test. **Birkin-Mnemosyne** (the memory
engine; "Mnemosyne" for short below) is built from the Python standard library
alone: Markdown notes in zone
directories, Okapi BM25 over a stat-fingerprinted inverted index, and a
usage-driven Ebbinghaus decay wired into the ranking. On LongMemEval-S session
retrieval it reaches **Recall@5 0.968 / MRR 0.91** (near-identical on the
cleaned and original splits: R@5 identical, MRR 0.910 vs 0.907) — beating a
same-harness *truncated* dense-embedding retriever (0.932 / 0.842), tying a
chunked one (0.968 / 0.908), and conceding only 0.009 R@5 / 0.021 MRR to the
best tuned hybrid we measured (0.977 / 0.931) — a margin that a dev-tuned,
arithmetic-only stack (query-side idf weighting, user-turn field weighting, a
relative-date prior; every ingredient classic IR) then buys back: **0.900 /
0.977 / 0.933**, parity with the hybrid, still with no encoder at all. An end-to-end check with a fixed cheap reader over the top-5
sessions answers 53.8 % of questions (abstention accuracy 0.80); an
oracle-evidence control shows the remaining bottleneck is the reader, not the
memory layer.

Second, **CurationPlan/1** makes agentic memory curation *safe and
provider-portable* by construction: the model emits only a typed JSON
reorganization plan, and a deterministic executor validates, clamps, and
applies it under file-safety invariants enforced in code. The same nightly
curation then runs across the Claude and Codex CLIs (with adapters for API,
Gemini, and local back-ends), and no output arriving through this interface —
however weak or adversarial — can delete a note, mass-archive the vault,
escape it, or archive a protected note (a model with other tool access is
outside this threat model). On a hard 232-pair curation benchmark scored with
a fixture-disjoint prompt over ten passes per engine, Claude sonnet leads
(link precision 0.851 [0.816–0.881] at recall 0.881), with haiku and Codex
competent but noisier — yet a hidden second fixture evaluated once shows the
engine *ordering* does not transfer across fixtures, while the safety
invariants hold for every pass from every engine. On a real 1,910-note vault,
one curation pass reorganizes structure dramatically (1 → 23 project zones,
29 → 3,485 links) while leaving frozen-query top-k retrieval essentially
unchanged — curation is an organizational win, not a reranking win. The idea
that transfers is a mechanical/judgment split applied over and over: let
arithmetic do what arithmetic can, enforce safety in code, and spend the model
only where judgment is genuinely required.

**국문 초록.** LLM 에이전트에 장기 기억을 부여하는 일은 갈수록 무거운 인프라를
쌓는 일이 되어 간다 — 임베딩 모델, 벡터 데이터베이스, 그래프 서버, 그리고 노트를
저장할 때마다 발생하는 LLM 호출까지. 본 논문은 사용자 한 명, 기계 한 대, 노트
수천 장 규모의 *개인* 에이전트에 그 스택이 정말로 필요한지를 묻고, 두 가지 주장으로
답한다.

첫째, 개인 규모의 검색에는 투명한 어휘 기반 기층(substrate)으로 충분하다.
**Mnemosyne**는 파이썬 표준 라이브러리만으로 구현한 기억 시스템으로, 노트는
구역(zone) 디렉터리에 놓인 마크다운 파일이고, 검색은 한글 바이그램 토크나이저를
갖춘 BM25 역색인이며, 망각은 간격을 둔 접근이 안정성을 키우는 에빙하우스 곡선을
랭킹에 직접 결합한 것이다. LongMemEval-S 세션 검색에서 이 기계적 계층만으로
Recall@5 0.968, MRR 0.91을 달성했으며(cleaned·original 두 스플릿에서 사실상 동일),
같은 하네스에서 측정한 절단(truncated) 밀집 임베딩 검색기(0.932/0.842)를 앞서고,
청크 임베딩과는 동률이며(0.968/0.908), 가장 강한 튜닝 하이브리드(0.977/0.931)에도
R@5 0.009·MRR 0.021만을 내준다 — 그리고 이 격차는 dev 절반에서만 튜닝한 순수
산술 스택(질의어 idf 가중, 사용자 발화 필드 가중, 상대날짜 사전확률 — 모두 고전
IR 기법)이 도로 회수한다: **0.900/0.977/0.933**, 인코더 없이 하이브리드와 대등. 고정된 경량 reader를 상위 5개 세션에 붙인 종단 간(end-to-end) 질의응답
검증에서는 53.8 %의 질문에 정답했고(회피 정확도 0.80), 정답 세션을 직접 제공하는
oracle 대조 실험은 남은 병목이 기억 계층이 아니라 reader임을 보여 준다.

둘째, **CurationPlan/1**은 에이전트 기반 기억 큐레이션을 구조적으로 안전하고
프로바이더 간 이식 가능하게 만든다. 모델은 typed JSON 재구성 계획만 출력하고,
결정적 executor가 코드로 강제되는 파일 안전 불변식 아래에서 그 계획을
검증·제한·적용한다. 그 결과 동일한 야간 큐레이션이 Claude와 Codex CLI에서(그리고
API·Gemini·로컬 어댑터를 통해) 실행되며, *이 인터페이스를 거치는 한* 아무리
약하거나 적대적인 모델 출력이라도 노트 삭제, vault 대량 아카이브, vault 밖으로의
이동, 보호 노트 아카이브를 일으킬 수 없다(다른 도구 접근 권한을 가진 모델은 이
위협 모델의 범위 밖이다). 정답 유출이 없는(fixture와 분리된 예시만 쓰는)
프롬프트로 엔진당 열 번씩 채점한 232쌍 하드 큐레이션 벤치마크에서는 Claude
sonnet이 앞섰지만(링크 정밀도 0.851 [0.816–0.881], 재현율 0.881), 단 한 번만
평가한 비공개 두 번째 fixture에서는 엔진 간 *순위*가 유지되지 않았다 — 반면 안전
불변식은 모든 엔진의 모든 실행에서 지켜졌다. 실제 1,910개 노트 vault에서는 큐레이션
한 번이 구조를 극적으로 재편하면서도(1개 → 23개 프로젝트 구역, 링크 29 → 3,485개)
동결 쿼리의 top-k 검색은 사실상 그대로였다 — 큐레이션의 가치는 재랭킹이 아니라
조직화에 있다. 이 논문을 관통하는 아이디어는 기계/판단의 반복적 분리다: 산술로
되는 일은 산술에 맡기고, 안전은 코드로 강제하며, 모델은 판단이 진정으로 필요한
곳에만 쓴다.

---

## 1. Introduction

The memory question for LLM agents is usually answered with more machinery.
MemGPT [2] pages context like an operating system; Mem0 [5] extracts facts with
LLM calls at write time into vector and graph stores; Zep [9] serves a
bi-temporal knowledge graph; HippoRAG [6] runs Personalized PageRank over an
LLM-built graph. These target products with many users and heavy query volume.
A *personal* agent — the setting of the Birkin project — has a different
profile: one user, a vault that grows by tens of notes a day, a single machine,
and a hard requirement that the user can open their memory in a text editor and
understand it.

Three observations shape our design.

1. **Most memory operations do not need a model.** Placing a note, indexing it,
   ranking by lexical relevance, tracking what gets used — these are mechanical.
   What needs judgment is sparse and batchable: which candidate links are real,
   which notes are misfiled, what has gone stale. A-MEM's ablations [1] show
   link generation and memory evolution are the components that matter; A-MEM
   performs those judgments online at write time, and we test whether they can
   instead be batched offline, off the hot path.

2. **Forgetting is a ranking signal, not a delete button.** MemoryBank [4]
   applies Ebbinghaus-style forgetting to an embedding store; rational analysis
   of human memory [17] says retrieval should track *need probability* —
   frequency, recency, spacing. We wire exactly that into the score.

3. **Spatial organization is cheap and humans already use it.** The method of
   loci is the one technique memory champions reliably share [18]. Zone
   directories give the same affordance to the user (folders in Obsidian) and
   the agent (a priority prior over places), at the cost of `mkdir`.

**Contributions** (in order of claimed importance).

- **CurationPlan/1**, a provider-portable, safe-by-construction curation
  interface: the model proposes a typed JSON plan; a deterministic executor
  validates, clamps, and applies it under file-safety invariants enforced in
  code (§3.3). Curation therefore runs identically across engines, and no
  model — however weak or adversarial — can violate those invariants: delete,
  mass-archive, escape the vault, or archive a protected note (§5.3–§5.6).
  What the interface cannot prevent is a bad-but-valid curation (a mis-merge,
  a wrong link, a spurious supersede marker); that residual is a
  model-accuracy question (§5.4), cleanly separated from safety.
- **A zero-dependency lexical memory substrate** — files in zones, a
  stat-refreshed inverted index, BM25 with a Hangul-bigram tokenizer,
  usage-driven decay, and zone priority — that reaches embedding-band recall on
  a public long-term-memory benchmark (§5.1) while staying greppable and
  diffable.
- **Decay and zone priority wired into ranking**, with ablations isolating each
  signal (§5.2).
- **An open, reproducible artifact**: a single-module retrieval engine, a
  curation executor and provider registry, 127 subsystem unit tests, and a
  deterministic benchmark harness.

**Positioning (what we do *not* claim).** We do not claim the first
memory-palace metaphor, the first local-first or file-based agent memory, the
first Ebbinghaus-style forgetting, or the discovery that BM25 is a strong
retriever — each has clear prior art (§2). To our knowledge the specific
*combination* is what is new: a **stdlib-only lexical substrate** (BM25 +
usage-driven decay + zone priority) paired with a **provider-agnostic,
plan-only curation interface whose file-safety is enforced by a deterministic
executor**. The load-bearing, empirically-supported claims are (i) that this
zero-dependency substrate reaches a competitive session-retrieval band without
any embedding stack (§5.1), and (ii) that moving safety from prompt-compliance
into a clamping executor makes curation safe *by construction* across engines
(§5.3) — not that any single ingredient is novel in isolation.

## 2. Related Work

**Agent memory systems.** MemGPT [2, R3] treats the context window as main
memory with paging to external storage; Mem0 [5, R6] extracts and consolidates
salient facts with LLM calls at write time over vector (and optionally graph)
storage; A-MEM [1] builds Zettelkasten-style atomic notes whose links the LLM
judges over embedding-retrieved candidates. MemoryBank [4] introduced
Ebbinghaus-inspired forgetting; SCM [10] puts a controller in front of a memory
stream; ReadAgent [11] compresses long documents into gists; HippoRAG [6] and
Zep/Graphiti [9, R4] sit at the knowledge-graph end. Surveys [15] taxonomize
the space. At the practitioner end sit open-source memory SDKs and platforms
(LangMem [R5], Cognee [R7], MemPalace [R1]) and self-curating agent skeletons
(Hermes-Agent [R2], whose curator lifecycle Birkin's skill aging follows).
Against all of these, our distinguishing choices are (a) no embedding model, no
vector store, no server — the substrate is files plus a JSON sidecar index —
and (b) LLM involvement only in a nightly batch, mediated by a deterministic
safety layer.

**The 2026 local-first / low-infra wave — and where we differ.** We are *not*
first to move agent memory onto local, human-readable files; a cluster of
concurrent work shares that instinct, and we position against it explicitly
rather than claim priority. **ByteRover** [21] is the closest: agent-native
memory in human-readable Markdown on the local filesystem, *no vector/graph
DB, no embedding service*, with importance scoring and recency decay — but the
same LLM that reasons also *curates and retrieves*, LLM judgment in the hot
path. Our inversion is the point: the model is reduced to a typed-plan
generator and a deterministic executor performs and bounds every file change
(§3.3, §5.3). **Infini Memory** [22] keeps text topic-documents consolidated by
periodic maintenance and agentic multi-step retrieval; we keep the substrate
verbatim and the retrieval a single mechanical BM25 pass. **Structured
Distillation** [24] targets the same one-user personal setting with thematic
"room" assignments, but *compresses* exchanges 11× into a retrieval layer
(and reports BM25 degrading under that compression) — we retain the full
Markdown vault and find lexical retrieval strong on it. **MemPalace** [R1]
popularized the local-first memory-palace metaphor and reports a high
LongMemEval retrieval band; an independent critical analysis [23] finds that
band comes largely from *verbatim storage plus ChromaDB's default embedding*,
not the spatial metaphor — which sharpens our contribution: we reach a
comparable session-retrieval band (§5.1) with **no ChromaDB, no embeddings,
no vector backend at all**. Finally, **Mnemosyne (edge LLM)** [20] shares only
our (former) name; it is a graph-structured, human-inspired store evaluated on
LoCoMo, architecturally disjoint from our stdlib lexical vault.

**Plan-then-execute safety.** CurationPlan/1's defense — the model only emits
a typed plan; deterministic code decides what runs — instantiates the
plan-then-execute pattern from the prompt-injection-defense literature: CaMeL
[19] interposes a capability-checked interpreter between an LLM planner and
tool effects, and the earlier dual-LLM proposals isolate a privileged planner
from a quarantined reader. Our setting is narrower (one nightly task, four op
types), which is what lets every invariant be enforced by clamping rather than
by policy checks at plan time.

**Cognitive grounding.** Ebbinghaus's forgetting curve replicates robustly
[13] — though that replication's own curve fitting favors power-law and
multi-exponential forms over a single exponential, so our per-note exponential
(§3.2) is an engineering simplification, with the spacing-grown stability σ
supplying the long-tail flattening those richer forms capture. The spacing
effect —
distributed practice slows forgetting — is among the best-established findings
in verbal memory [14]; our stability multiplier fires only when accesses are
≥1 h apart. Anderson & Schooler [17] showed memory availability tracks
environmental need probability, precisely the statistic our effective-strength
boost estimates. Generative Agents' retrieval score — an equally weighted sum
of recency, importance, and relevance [3] — is the closest scoring ancestor;
we replace LLM-scored importance with usage-earned strength and embedding
relevance with BM25.

**Benchmarks.** LoCoMo [7, D2] evaluates QA over very long multi-session dialogues;
LongMemEval [8] provides 500 questions over multi-session haystacks (≈48
sessions per question, 38–62, measured in our harness) with labeled evidence
sessions, and is our retrieval target. The probabilistic-relevance framework
[12] is the canonical reference for the BM25 ranking we implement; retrieval-
augmented generation [16] is the standard downstream consumer of the session
localization we evaluate. A concurrent systems-characterization study [25]
profiles ten existing memory systems and independently reports flat BM25
beating dense retrieval on the LongMemEval/MemoryAgentBench family (55.8 % vs
39.8 % macro accuracy in their harness), that the *write path* dominates
total energy across systems, and that **none of the ten implements forgetting
by default** — three findings that respectively corroborate our lexical
substrate (§5.1), our mechanical write path with nightly-batch-only LLM use,
and the usage-driven decay this system wires into ranking (§3.2).

## 3. System

### 3.1 Host: Birkin, and skills as procedural memory

Mnemosyne is the declarative-memory subsystem of **Birkin**, an open-source
(MIT) personal agent that itself runs from the Python standard library alone: an
agent loop with a tool registry, a provider abstraction (Anthropic/OpenAI APIs
or subscription CLIs such as Claude Code and Codex), a Telegram/HTTP gateway,
depth-bounded subagents, an approval queue, and a scheduler. Birkin's *other*
memory is **skills** — procedural memory stored as `SKILL.md` files that the
agent can author and refine, aged by a curator (30-day stale, 90-day archive).
The judgment layer described below, **Morpheus**, is itself packaged as a Birkin
skill: a thin nightly launcher plus a `SKILL.md` procedure. One design rule
runs through everything: mechanical code handles whatever does not need
judgment, and the model is called only where it does — first in retrieval
(§3.2), then in curation (§3.3).

### 3.2 The retrieval substrate

A **zone** is a one-level directory under the vault (`projects/`, `people/`,
`knowledge/`, …) — the memory-palace room. The vault root is the *inbox*;
`_archive/` is the soft-forget room, excluded from retrieval by default. New
notes are placed by a type→zone map; placement is *refined*, not decided, by the
LLM later (§3.3).

The **index** is a JSON sidecar cache: per note, a stat fingerprint (mtime,
size), frontmatter metadata, outgoing wikilinks, and a term-frequency map. A
refresh is an `os.scandir` stat pass — only files whose fingerprint changed are
re-read and re-tokenized — so retrieval and rendering never re-parse the whole
vault, and externally edited notes (the user typing in Obsidian) are visible
immediately. Usage state (dynamics, zone EMAs) lives in a *separate* sidecar
that survives index rebuilds: the index is a cache, dynamics are state.

The **tokenizer** lowercases ASCII words and, for Hangul runs, emits the run
plus all character bigrams (`"메모리"` → `메모리, 메모, 모리`) — substring-level
recall for Korean without a morphological analyzer. Scoring is Okapi BM25 [12]
with k1 = 1.5, b = 0.75.

**Dynamics.** Each note carries `(strength s, stability σ, access_count,
last_access)`, initialized to (1.0, 7 d, 0, created). Its effective strength at
time *t* is the Ebbinghaus retention

> eff(t) = max(0.05, s · exp(−Δdays(t, last_access) / σ)),

floored so nothing becomes unreachable. An **access** — reading a note in full,
or writing it; browsing a result list does not count — potentiates it:

> s ← min(5.0, s + 0.25);  if Δh ≥ 1: σ ← min(365, σ · 1.5).

The spacing gate follows Cepeda et al. [14]: only distributed accesses grow
stability, multiplicatively, so a handful of spaced touches buys months of
retention (§5.2). Each access also bumps its zone's EMA (decayed 0.9/day).
Birkin injects a standing **prompt digest** into the agent's system prompt — a
capped, zone-aware summary of the vault, zones ordered by normalized EMA
priority and notes within a zone by effective strength, inbox last, `_archive`
excluded. Notes carrying `polarity: negative` (recorded failures) are tagged in
the digest with a "⚠ known failure — re-verify" annotation (evaluated in §5.7).
Zone priority thus both orders the digest and boosts retrieval.

**Ranking.** For a query *q* at time *t*,

> score(n) = BM25(n, q) · (1 + 0.3 · eff(n, t)/5 + 0.2 · priority(zone(n))).

Relevance dominates (the boost is bounded by ×1.5); usage and place warm the
ranking and break lexical ties. TTL-expired and archived notes are skipped;
snippets are read only for the top-k hits.

**Staleness** is derived, not stored: eff < 0.1 and > 90 days without access —
the feed the nightly curator (§3.3) considers for archival.

### 3.3 CurationPlan/1: a provider-portable curation interface

Mnemosyne's nightly reorganization — file inbox notes into zones, link related
notes, mark superseded facts, archive stale ones — needs judgment, so it needs
a model. The naive way to support many engines fails badly. When we first ran
curation on OpenAI's Codex, Birkin handed the whole turn to `codex exec`, which
runs *its own* tools with no access to Birkin's; it acted on the vault with raw
shell moves and, across runs, either did nothing, moved *every* note —
including a protected control zone — into `_archive/`, or, in one run, removed
all 21 notes from the vault outright while parroting the injection canary
planted in the conversation history. Safety had been left to the model's
prompt-following, and a differently-tuned model did not comply.

**CurationPlan/1** fixes this by applying the mechanical/judgment split to the
interface itself. Every provider reduces to one contract:

> `complete(prompt: str) -> str`

The model is a pure text generator. It never touches the vault, tools, or a
shell; it emits exactly one JSON **CurationPlan** — a list of typed ops
(`rezone`, `link`, `supersede`, `archive`) referencing notes by their existing
slug. A deterministic, stdlib executor then does all the work: it parses the
plan (unparseable output degrades to an empty plan — a safe no-op), *validates
and clamps* it against a pre-run snapshot the model cannot forge, and applies
only the survivors through the index. Because prompt, schema, gate, and scorer
are shared, every model runs the identical task and results are comparable by
construction.

The **file-safety invariants** are enforced in code, so a weak or adversarial
model cannot corrupt or destroy the vault, whatever plan it emits:

1. **Never delete** — the schema has no delete op; `archive` only *moves* a note
   to `_archive/`.
2. **Archive cap** — at most `max(2, ⌈0.20·active⌉)` archives per pass, applied
   to the mechanically weakest notes; the overflow is dropped.
3. **Protected notes** — `polarity: negative` warnings, filed-and-linked control
   notes, and configured types are never archived.
4. **`_archive` is not a topical zone**; **path containment** — every op must
   name a known slug, and every move stays under the vault.
5. **Summary is inert** — the model's free text is never a control signal; an
   injection canary can only surface as archive ops (absorbed by 1–3), and the
   forbidden phrase is Unicode-normalized and sanitized from the audit record.

**Why these hold (argument sketch).** The op vocabulary is closed and dispatch
is total: parsing yields either a list of the four typed ops or — for anything
else — an empty plan, so every reachable vault mutation factors through one of
four handlers. Each handler preserves the invariants locally: none unlinks a
file (1); archive runs behind a cap computed from a pre-run snapshot the model
cannot forge (2) and a protected-note check (3); every target must match a
snapshot slug and every destination stays under the vault root (4); the
summary string is data, never control (5). Invariant preservation is thus a
property of executor code, under two stated assumptions: the executor is the
sole write path during a pass, and the host filesystem is trusted —
symlink/race (TOCTOU) hardening and crash-atomicity across a multi-file pass
are engineering concerns outside these claims.

**Dense linking is mechanical too.** After the model assigns zones, the executor
adds reciprocal links between all notes co-placed in a touched zone. The model
does the *judgment* (which zone each note belongs to); the executor does the
*arithmetic* (link all same-zone pairs). Link accuracy therefore becomes a pure
function of placement accuracy — a property §5.4's metrics are defined around —
and cross-zone or inbox notes are never linked.

**Provider adapters** are the entire model-specific surface — each configures an
engine into a safe, plan-only mode, then hands text to the shared executor:

| provider | invocation | prompt in | can it write the vault? | plan-format constraint | config isolation |
|---|---|---|---|---|---|
| **claude** | `claude -p --output-format json` | stdin | no (`--allowedTools ""`) | prompt-specified | default |
| **codex** | `codex exec --sandbox read-only --output-schema S` | stdin | **no (read-only sandbox)** | **enforced JSON schema** | isolated `CODEX_HOME`, `--ignore-user-config`, `--cd <vault>` |
| **api** | Anthropic/OpenAI via `LLMClient` | messages | n/a (no tools) | prompt-specified | n/a |
| **gemini** | `gemini -p -` | stdin | CLI default | prompt-specified | n/a |
| **local** | `ollama run <model>` | stdin | n/a | prompt-specified | n/a |

Codex needs the most configuration because it is an agentic coding CLI, not a
text endpoint: without `--sandbox read-only` it rewrites files instead of
proposing; without `--output-schema` it replies with clarifying prose instead of
a plan; without an isolated home and `--cd <vault>` it inherits the user's slow
reasoning config and reads unrelated project files. Once wrapped this way it
emits schema-valid plans in ~1–2 minutes. The invariant across all engines:
whatever the model is, it can only *propose*; the deterministic layer decides
what happens, and the CLI (`birkin curate-memory --provider …`) records a
before/after SHA-256 manifest so every pass is a reviewable, tamper-evident
diff — moves are reconstructible from hash identity and content appends are
detectable; undoing a content edit relies on external versioning of the vault
(e.g. git), which the CLI itself does not provide.

### 3.4 Implementation

The retrieval engine (`mnemosyne.py`) is a single ~680-line module; the curation
executor and provider registry add ~800 lines across focused modules. 127 unit
tests cover the memory and curation subsystems (636 in the full repository
suite): pure functions with exact values, index incrementality (touch one file
→ one re-parse), a gateway thread-race fixed by an adversarial review, zones,
Korean round-trips, and the curation gate — including adversarial plans
(archive-everything, invented slugs, unhashable op fields, canary homoglyphs)
that a separate adversarial-review pass surfaced and that are now
regression-pinned. The suite passes under the repository's ≥75 % coverage gate.

## 4. Evaluation setup

All numbers come from the committed harness. The **substring baseline** is
Birkin's own pre-Mnemosyne search — read and parse every note, rank by raw
substring counts — the honest "before". Environment: Windows 11, Python 3.13.

- **§5.1 LongMemEval-S** [8]: for each of the 470 non-abstention questions, rank
  its haystack sessions (≈48 per question, 38–62) by BM25 (pure functions, no
  dynamics/zones — isolating the mechanical relevance layer) against the
  question text; report session-level Recall@k / MRR. Both the cleaned [D1] and
  the original dataset splits are run with the same harness.
- **§5.2 Synthetic H1–H5 and extensions**: seeded, offline. Efficiency (index
  vs full-scan at 100/500/2000 notes); English and Korean retrieval on
  planted-token corpora; a 2×2 dynamics/zone-priority ablation on identical-body
  note pairs; decay trajectories; a realistic Korean/mixed-language retrieval
  comparison of BM25+bigram against `multilingual-e5-large`; and the
  same-harness embedding baselines of §5.1 (bge-small and an RRF hybrid, with a
  larger bge-large as a robustness check, plus review-driven stronger
  configurations: chunked embeddings, a swept fusion constant, and
  BM25→dense reranking).
- **§5.3–§5.6 Curation**: a labeled fixture (topical clusters, a no-op control
  zone, duplicate/contradiction/negative/stale notes, and a prompt-injection
  canary) and a **hard fixture** (13 clusters with cross-cluster vocabulary
  overlap → 232 intra-cluster pairs, plus 15 distractor singletons), run **ten
  times per engine** with bootstrap CIs; a **hidden fixture B** (10
  domain-disjoint confusable clusters → 110 pairs + 12 distractors) authored
  after the prompt was frozen and evaluated exactly once per engine; and a
  **real 1,910-note vault** with 40 paraphrase queries frozen before curation.
  Scored from the on-disk vault — before/after SHA-256 snapshots for the
  labeled fixture, a post-pass re-index of zones and links against fixture
  ground truth for the hard fixture — never the agent's own report.
- **§5.1 end-to-end QA**: BM25 top-5 (or labeled oracle evidence) → haiku
  reader (answers from provided history only, abstains otherwise) → sonnet
  judge vs gold, one word yes/no; abstention questions correct iff abstained;
  per-question records retained for audit (`bench_lme_e2e.py`).
- **§5.3 Safety defense-layer ablation**: five attack plans (mass-archive,
  archive-protected, path-traversal, invented slugs, injection canary) replayed
  through three defense levels (raw apply / schema-only / full executor) on a
  6-note vault with one protected note; vault damage measured from disk.
- **§5.7 Negative-memory probe**: a one-turn decision task (`deploy.sh --ftp`
  vs `--rsync`, answer constrained to a CHOICE/REASON pair) with the memory
  digest injected as the system prompt, under three conditions — warned
  (negative note), transient-failure, no-memory — haiku, 6 trials per
  condition, scored mechanically by regex; raw outputs retained for audit.

## 5. Results

### 5.1 LongMemEval-S session retrieval

The mechanical layer localizes the evidence session for the overwhelming
majority of questions. We compare, in the *same harness over the identical
sessions*, our BM25 engine against a dense-embedding retriever
(BAAI/bge-small-en-v1.5, cosine over L2-normalized session vectors), a
reciprocal-rank-fusion hybrid of the two (RRF, k=60), and the substring search
Mnemosyne replaced (n=470 non-abstention questions, cleaned split):

| system | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|
| **BM25 + bigram (ours)** | **0.870** | **0.968** | 0.981 | 0.910 |
| dense embedding (bge-small) | 0.770 | 0.932 | 0.966 | 0.842 |
| dense embedding (bge-large) | 0.783 | 0.936 | 0.966 | 0.849 |
| hybrid (RRF BM25+embed) | 0.868 | 0.966 | **0.989** | **0.914** |
| substring (prior system) | 0.089 | 0.343 | 0.577 | 0.223 |

Two readings. First, **the stdlib lexical engine matches or beats these
standard dense configurations**: BM25 leads the whole-session embedding
retriever by +0.10 R@1 and +0.068 MRR, and the k=60 hybrid over it buys
essentially nothing over BM25 alone (ΔMRR +0.004, ΔR@5 −0.002). *Scaling the
encoder does not rescue it*: the larger bge-large lands at R@5 0.936 / MRR
0.849 — +0.004 / +0.007 over bge-small and still −0.032 R@5 / −0.061 MRR
behind BM25. What closes the gap is not scale but *chunking* — see the
stronger baselines below. The flat-BM25-beats-naive-dense direction is not an
artifact of our harness: a concurrent ten-system characterization study [25]
independently finds flat BM25 beating dense retrieval on the same benchmark
family (55.8 % vs 39.8 % macro in their end-to-end harness). And the substring
row shows the band is not free either: tokenization, idf, and length
normalization carry it.

One input-fairness caveat, measured rather than waved at: sessions were
truncated to 6,000 characters for embedding (bge-small's 512-token window
would truncate further regardless), while BM25 read full text. Re-running BM25
on the *identical truncated text* still beats the embedding retriever — R@5
0.953 vs 0.932, MRR 0.887 vs 0.842 — so the lexical win is not an artifact of
input length; full-text access then gives BM25 a further +0.015 R@5 that a
512-token encoder structurally cannot use.

**Stronger dense baselines (review-driven).** The baselines above encode each
session as one truncated vector — a reviewer correctly flagged that as weak.
We therefore ran the standard fixes in the same harness over all 470
questions: chunked embeddings (bge-small, 1,200-char chunks, 200 overlap,
session score = max chunk cosine), RRF with the fusion constant swept instead
of fixed, and BM25→dense reranking:

| stronger dense config (same harness) | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|
| BM25 (reference) | 0.870 | 0.968 | 0.981 | 0.910 |
| chunked dense, max-pool | 0.855 | 0.968 | 0.981 | 0.908 |
| hybrid RRF k=20 (BM25+chunked) | **0.894** | **0.977** | **0.994** | **0.931** |
| hybrid RRF k=60 / k=120 | 0.894 | 0.974 | 0.991 / 0.989 | 0.930 |
| BM25 → dense rerank (top-20) | 0.862 | 0.972 | 0.983 | 0.912 |

This upgrades the honest summary in two ways. First, **the dense gap was a
truncation artifact**: chunked bge-small ties BM25 (R@5 identical, MRR
−0.002), so "lexical beats dense" holds only against whole-session
truncation — properly chunked, the two are equivalent here. Second, **fusion
buys a small, real gain**: RRF over BM25 + chunked dense adds +0.024 R@1 /
+0.009 R@5 / +0.021 MRR over BM25 alone, and is insensitive to the fusion
constant across k=20–120. We therefore *retire* the earlier claim that the
evaluated embedding configurations added nothing. The claim that survives is
narrower and still substantive: **BM25 alone concedes at most ~0.01 R@5 /
~0.02 MRR to the best embedding-backed configuration we measured, while
requiring no encoder, no vector store, and no model at query time.** At
personal scale that trade remains, in our judgment, the right default — and
the hybrid stays available over the same substrate for deployments that want
the margin. (A late-interaction / ColBERT-class retriever and long-context or
task-tuned embedders remain unrun; §7.)

**A tuned lexical stack closes the hybrid gap.** The RRF margin above prompted
one more arithmetic-only round: does BM25 lose to the *embedding*, or merely
to *tuning*? We split the 470 questions into a dev half (tuning allowed) and a
frozen test half, swept on dev only, and froze one configuration: BM25F-style
**user-turn field weighting** (user-turn tf ×3 — the questions ask about the
*user*; cf. the benchmark authors' user-fact key expansion [8]),
collection-tuned k1=0.9 / b=0.5, **query-side idf weighting** (each query term
weighted by its own idf — the classic SMART ltc query weighting [26] applied
to BM25, so rare anchors dominate conversational filler), and a
**relative-date prior** (a Gaussian window over session dates when the query
parses to "N weeks ago" / "last Saturday" — a mechanical variant of time-based
language models [27] and of the time-aware retrieval the benchmark itself
proposes [8]):

| tuned lexical vs hybrid (n=470) | R@1 | R@5 | R@10 | MRR |
|---|---|---|---|---|
| BM25 (untuned reference) | 0.870 | 0.968 | 0.981 | 0.910 |
| hybrid RRF k=20 (best swept) | 0.894 | 0.977 | **0.994** | 0.931 |
| **tuned lexical stack (ours)** | **0.900** | **0.977** | 0.981 | **0.933** |

Every ingredient is classic IR — we claim the measurement, not the mechanisms.
The empirical point is that their combination buys back the entire hybrid
margin on this benchmark: R@1 +0.006 and MRR +0.002 over the best swept
hybrid, R@5 tied, still with no encoder, no vector store, and no model at
query time (R@10 is where the hybrid keeps an edge, 0.994 vs 0.981). Protocol
honesty: on the untouched test half the frozen stack scores R@1 0.885 / R@5
0.979 / MRR 0.923 — below the hybrid's full-set point on R@1/MRR — and the
full-set margins are ~3 questions wide, so the defensible claim is *parity
with* the tuned hybrid, not dominance; the hybrid's fusion constant was
itself selected post-hoc on the full set, which makes full-vs-full the
symmetric comparison. Branches that did not survive dev, reported so nobody
retries them blind: lexical chunk max-pooling (the fix that rescued dense
embeddings *hurts* lexical ranking), span proximity (global and as a
tie-break), RM3 pseudo-relevance feedback (recovers tail recall, scrambles
top-1), and a word-bigram phrase field. Reproduce:
`benchmarks/sweep2_ranking_v2.py --split full`.

Second, the result is split-robust: on the original (uncleaned) split BM25
scores R@1 0.864 / R@5 0.968 / MRR 0.907, a negligible delta from the cleaned
split. By question type (BM25 R@5, cleaned): knowledge-update 1.00,
single-session-user 1.00, single-session-assistant 1.00, multi-session 0.959,
temporal-reasoning 0.953, single-session-preference 0.867.

**From retrieval to answers (end-to-end QA).** Localizing the session is not
the same as answering the question, so we close the loop with a fixed-reader
pipeline: BM25 top-5 sessions (capped at 12k chars each, with session dates) →
a **haiku reader** instructed to answer only from the provided history and to
abstain otherwise → a **sonnet judge** grading the answer against the gold
(LongMemEval-style model judging; abstention questions are correct iff the
reader abstained). All 500 questions of the cleaned split:

| BM25 top-5 → haiku reader | n | accuracy |
|---|---|---|
| answerable questions | 470 | **0.538** |
| abstention questions | 30 | **0.80** |

By type: single-session-assistant 0.75, single-session-user 0.72,
temporal-reasoning 0.56, knowledge-update 0.54, multi-session 0.41,
single-session-preference 0.20. The profile is the expected one for a small
reader: single-evidence questions land, multi-session aggregation and
preference questions (which need a persona-style answer our prompt does not
elicit) suffer.

The instructive number is the gap: retrieval finds the evidence for 96.8 % of
questions, yet the pipeline answers 53.8 % — **at this design point the
binding constraint is usually the reader, not the memory layer**. An
oracle-evidence control decomposes the two losses by handing the reader the
*labeled* evidence sessions instead of BM25 top-5:

| condition | single-session-user (n=64) | multi-session (n=36) |
|---|---|---|
| BM25 top-5 → reader | 0.72 | 0.41 |
| oracle evidence → reader | **0.80** | **0.67** |

The decomposition is the point. For single-evidence questions the reader with
top-5 is already near its oracle ceiling (0.72 vs 0.80) — retrieval costs only
~8 points and the reader is the binding constraint. For **multi-session**
questions the gap is large (0.41 vs 0.67): even with the evidence in hand the
small reader answers only two-thirds, but retrieval *also* costs ~26 points,
because these questions have several evidence sessions and top-5 misses some —
exactly where a higher k or a stronger aggregating reader would pay off. We
deliberately used the cheap on-device-class reader consistent with the paper's
design point; a stronger reader raises the ceiling without changing the memory
system underneath.

The reader role is provider-agnostic through the same adapter registry as
curation (§3.3). A follow-up `n=20` oracle-evidence smoke with Codex readers
(judge: Claude haiku) confirms this and shows a stronger reader lifts accuracy:
gpt-5.3-codex-spark 0.90, gpt-5.4 0.95, gpt-5.5 0.90 answerable accuracy — above
the cheap-haiku oracle baseline. The same batch re-ran the larger embedding
encoders on `n=20`: BM25 R@5 1.00 vs bge-large 0.75 and multilingual-e5-large
0.75, hybrid ≤0.95 — BM25 ahead of every truncated configuration, matching
the direction of the full 470-question sweep (where only chunking closes the
gap; §5.1).
These are `n=20` smokes, not headline benchmarks; raw results are attached in
`evidence/codex-matrix-20260707/` (see its `INDEX.md`). A full Codex-reader run
remains future work.

Scope: the retrieval table above is *session localization*; the end-to-end
numbers are for our own fixed pipeline, and we still make no cross-system QA
comparison against Mem0, Zep, or similar — their published numbers use
different readers and protocols. §6 discusses comparability.

### 5.2 Efficiency, retrieval quality, and ablations (synthetic)

**Efficiency (H1).** The index answers queries 7.8–9.9× faster than the full-scan
baseline at every size, and the steady-state stat refresh stays ~100 ms even at
2000 notes:

| notes | warm refresh (ms) | index search (ms/q) | naive search (ms/q) | speedup |
|---|---|---|---|---|
| 100 | 4.0 | 4.6 | 45.1 | ×9.9 |
| 500 | 36.9 | 36.9 | 288.1 | ×7.8 |
| 2000 | 101.0 | 115.9 | 1102.8 | ×9.5 |

**Context-token cost (measured 2026-07-12).** Latency is not the binding
budget for an LLM agent — prompt tokens are. We therefore measured what each
memory strategy actually puts into the model's context (chars/4 estimator,
reported alongside raw chars so any tokenizer can be substituted; no LLM
calls). On LongMemEval (470 questions), the long-context alternative — every
haystack session in the prompt — costs a mean **122k tokens per question**
for guaranteed evidence coverage; retrieval-based top-5 costs **13.5k
(9.1×less) at 0.977 coverage** (tuned lexical ranking; plain BM25 13.4k at
0.968 — better ranking is token efficiency, not just recall), top-3 costs
8.2k at 0.960, and the oracle floor is 5.3k. On the real 1,910-note vault the
comparison is not close: loading the vault wholesale would cost **2.96M
tokens — beyond any current context window** — while what Mnemosyne actually
injects per query (the 0.9k-token always-on digest + top-8 result metadata +
the three opened note bodies) averages **8.0k tokens, a 371× reduction**.
This is the token-cost face of the index-only design: the model never pays
for notes the postings did not match. Reproduce:
`benchmarks/bench_token_cost.py`.

Could snippets replace the opened bodies and cut the 8k further? Measured,
and **no** — an honest negative: injecting 600-char best-window snippets
instead of full sessions cuts context ×14.7 (8.3k → 0.57k on top-3) but
halves end-to-end answer accuracy (0.417 → 0.233; abstentions 4 → 26 of 60,
haiku reader / sonnet judge, dev sample) — the answer sentence is too often
outside any fixed window. Snippets therefore serve as the *search preview*
layer (multi-term best-window, `memory_search`), while full-note reads stay
an explicit on-demand tool call: the 8k figure is the pay-when-needed cost of
answers, not overhead a cleverer window can remove. Reproduce:
`benchmarks/bench_snippet_e2e.py`.

**Retrieval quality (H2, H2b).** With planted rare anchor tokens, BM25 lifts the
target over notes that merely repeat common words, and Hangul bigrams close the
gap for Korean without language tooling:

| corpus | system | R@5 | MRR@10 |
|---|---|---|---|
| English | BM25 | **0.983** | 0.893 |
| English | substring | 0.483 | 0.236 |
| Korean | BM25 + bigram | **0.983** | 0.898 |
| Korean | substring | 0.542 | 0.319 |

The Korean row is a *synthetic* probe that the Hangul-bigram tokenizer recovers
Korean queries where a whitespace/substring tokenizer fails — not a claim of
general Korean IR quality. To pressure-test the tokenizer against a *real*
semantic model, we ran a second Korean experiment: 16 realistic Korean topic
notes, three query styles (exact Korean phrase, partial/reworded Korean cue,
and Korean–English code-switched), BM25+bigram vs the multilingual encoder
`intfloat/multilingual-e5-large`:

| Korean query style | BM25 + bigram R@5 | multilingual-e5 R@5 |
|---|---|---|
| exact | 1.00 | 1.00 |
| partial (reworded) | 1.00 | 1.00 |
| mixed (Korean+English) | 0.94 | 1.00 |

The bigram engine ties the multilingual model on monolingual Korean queries;
the model's only edge (small n) is **code-switched** queries, where an English
word must map to a Korean concept — exactly the cross-lingual case a lexical
tokenizer cannot bridge and where an embedding re-ranker would earn its keep
(§6). Relatedly, dropping the Hangul bigrams from the tokenizer leaves the
English LongMemEval numbers (§5.1) unchanged to three decimals, confirming the
bigrams are a Korean-only feature that costs English nothing.

**Ablations (H3, H4) — a 2×2 over both signals.** We toggle both boost weights
independently on one vault of identical-body twin notes: twin A is rehearsed
(5 spaced accesses) and lives in a hot zone, twin B is untouched in a cold
zone. The metric is the fraction of pairs where A ranks strictly above B via
the real `search`:

| ranking | a-above-b | ties |
|---|---|---|
| BM25 only (W_DYN=0, W_ZONE=0) | 0.00 | 1.00 |
| BM25 + decay (W_DYN=0.3) | 1.00 | 0.00 |
| BM25 + zone (W_ZONE=0.2) | 1.00 | 0.00 |
| BM25 + decay + zone | 1.00 | 0.00 |

With identical bodies BM25 is a dead tie on every pair (0.00); *either* signal
alone breaks it deterministically, and together they compound. The boosts do
exactly what they are for, and nothing when there is no usage/zone signal to
apply.

**Sensitivity: what the boosts cost (interference).** The 2×2 shows benefit;
a fair criticism is that usage boosts create a rich-get-richer failure mode —
a frequently-touched but less-relevant note outranking a cold but correct one.
We measured this directly: 30 target/decoy pairs where the *decoy* is heavily
rehearsed (5 spaced accesses) and lives in a hot zone while the target is
cold, swept over a 5×4 grid of (W_DYN, W_ZONE) from (0,0) to (1.0,0.4). With a
**clear relevance gap** (target strongly on-topic, decoy tangential), the
target wins **100% of pairs at every grid point including the extremes** — the
multiplicative boost is bounded (×1.5 at maximum strength and defaults), so it
structurally cannot flip an order-of-magnitude BM25 gap. Interference is
confined to the **near-tie band**: on marginal pairs (decoy nearly as relevant
as the target), the rehearsed decoy wins most pairs at default weights (target
survival 0.067 at W_DYN=0.3, W_ZONE=0.2) and progressively fewer as weights
shrink. Meanwhile the tie-break *benefit* (identical twins) is already
saturated at W_DYN=0.1, W_ZONE=0.1 (warm twin wins 1.00). The design
implication is honest and actionable: the defaults buy their tie-breaking at
the price of re-ordering genuine near-ties toward recently-used notes — which
is the intended personalization behavior, but a deployment that prizes strict
lexical faithfulness can halve both weights and lose nothing on the twin
benefit.

**Decay (H5).** Effective strength by day, for three archetypes:

| archetype | d0 | d7 | d30 | d90 | d180 | eff<0.1 at day |
|---|---|---|---|---|---|---|
| never accessed | 1.00 | 0.37 | 0.05 | 0.05 | 0.05 | 17 |
| one write | 1.25 | 0.46 | 0.05 | 0.05 | 0.05 | 18 |
| five spaced touches | 2.25 | 1.97 | 1.28 | 0.41 | 0.08 | **166** |

Five spaced touches (σ grows 7 → 53 d) keep a note retrievable for ~166 days;
an untouched note fades toward the floor in ~2–3 weeks. Archival additionally
requires 90 days without access, so a well-rehearsed note is not even an archive
*candidate* until ~month 6.

### 5.3 Curation safety (adversarial review)

An adversarial-review pass fired a battery of crafted malicious plans at the
executor — mass-archive, invented and path-traversal slugs, malformed and
unhashable op fields, canary homoglyph variants — now pinned as regression
tests in the suite. The file-safety invariants (never-delete, archive-cap,
protected-notes, path-containment) held in every case: a plan that archives
*every* note is clamped to the cap on the weakest non-protected notes; invented
or path-traversal slugs are dropped; a canary in the untrusted transcript can
only surface as archive ops, which the gate absorbs. The review also found two
*non-destructive* defects — a crash on an unhashable op field (availability) and
a canary-phrase sanitizer bypassable by homoglyph/zero-width variants (audit
hygiene) — both since fixed and regression-pinned. Across every
CurationPlan/1-mediated run in this paper, including the noisy ones below, no
pass ever deleted a note, escaped the vault, or mass-archived it — in contrast
to the pre-CurationPlan/1 runs of §3.3, where one raw-tool codex pass removed
the entire vault.

**Safety comes from the layer, not the schema (ablation).** To locate *where*
the protection lives, we replay five attack plans through three defense levels
on a 6-note vault (one `polarity: negative` protected note): **raw** (apply the
plan's moves directly — the "trust the model" baseline), **schema-only**
(accept structurally well-formed ops referencing real slugs, but no clamp), and
**full** (the CurationPlan/1 gate). "GONE" means the protected note was
archived; "capped" means only the archive-cap survivors were moved:

| attack | raw | schema-only | full executor |
|---|---|---|---|
| mass-archive-all | all 6 archived, protected GONE | all 6 archived, protected GONE | capped at 2, protected safe |
| archive-protected-note | protected GONE | protected GONE | **intact** |
| injection-canary plan | all 6 archived, protected GONE | all 6 archived, protected GONE | capped at 2, protected safe |
| path-traversal zone/slug | intact | intact | intact |
| invented slugs | intact | intact | intact |

The discriminating rows are the first three: **a JSON schema does not stop a
mass-archive** — every op is individually well-formed — so schema validation
alone leaves the vault as exposed as raw execution; only the executor's
archive-cap and protected-note clamp hold. The last two rows are honest
nulls: path-traversal is neutralized one layer *below* the gate (Mnemosyne's
`rezone` sanitizes the zone and keeps moves inside the vault), and invented
slugs are inert because they match no file. Protection is thus a property of
the deterministic executor plus the file mover — never of the model output or
its schema.

**A curation floor.** To calibrate the §5.4 accuracy numbers, the trivial
baselines: doing nothing yields link recall 0.0 (no links), and randomly
assigning the 75 hard-fixture notes to 8–13 zones and dense-linking yields
recall 0.08–0.10 at precision 0.04–0.05 with 100+ distractor links. Any model
result well above that floor reflects real placement judgment, not the
executor's linking mechanics.

### 5.4 Curation accuracy across engines

Because the executor densely links all co-placed notes (§3.3), the
hard-fixture link metrics measure *placement* pairwise: **link recall** is
co-placement completeness over the fixture's intra-cluster pairs, and **link
precision** is cluster purity — the fraction of all links a pass created that
are true intra-cluster pairs. They are not an independent judgment of
"relatedness"; they are the placement axis, scored at pair granularity.
Alongside them we score *lifecycle* (duplicate/contradiction/stale handled)
and *safety*. On hard data precision is the discriminating metric: mis-merging
two clusters wrongly links every pair across them, and a "link everything"
policy maximizes recall while destroying precision.

On the easy labeled fixture (18 intra-cluster pairs, unambiguous placement),
Claude sonnet and haiku both reach link recall **1.00** — correct placement
plus the dense-linking executor make this table stakes. The interesting
question is the hard fixture.

The **hard fixture** (232 pairs; clusters that share vocabulary — three
networking families, Postgres vs MySQL tuning, sourdough vs pizza dough,
running vs cycling — plus 15 distractors that must stay unlinked) stresses
placement. A methodological confession shapes how we report it: **our first
prompt iterations leaked the answer key.** While tuning placement guidance we
added exemplars that named this fixture's own cluster boundaries ("Postgres
tuning and MySQL tuning are two zones; sourdough bread and pizza dough are
two; …"), which contaminates the benchmark — those runs scored higher (e.g.
sonnet 0.91 recall / 0.87 precision; codex 0.87 / 0.85) and we exclude them
all. The final prompt keeps only fixture-disjoint guidance (judge by note
content, not shared keywords; split sibling variants — with exemplars from
domains absent from the fixture; leave true one-offs in the inbox; treat BM25
neighbours as weak keyword hints). With the fixture-disjoint prompt, over
**ten independent passes per engine** (bootstrap 95% CIs, 10k resamples):

| hard fixture (232 pairs), n=10 | link recall | link precision | distractor links | wall time |
|---|---|---|---|---|
| **Claude · sonnet** | 0.881 [0.836–0.923] | **0.851 [0.816–0.881]** | ≤3 | 5.9 ± 1.1 min |
| **Claude · haiku** | 0.825 [0.706–0.913] | 0.769 [0.728–0.811] | ≤105* | 4.2 ± 1.1 min |
| **Codex · gpt-5.3-codex-spark** | 0.853 [0.804–0.896] | 0.732 [0.714–0.752] | ≤12 | **1.5 ± 0.7 min** |

\* one haiku pass linked distractors en masse (105 links touching distractor
notes in a single run) — an outlier, but we report it; the executor's
invariants held throughout (no deletion, archive cap respected).

The honest reading, on this fixture. **sonnet is the strongest curator** — its
precision CI [0.816–0.881] does not overlap haiku's [0.728–0.811] or codex's
[0.714–0.752]; **haiku matches on average but swings wildly** (recall SD 0.182,
range 0.36–0.97 across ten passes); **codex is competent, fastest, tightest**
(precision SD 0.032) **and no longer privileged** — its contaminated-prompt
precision advantage (0.85) collapses to 0.73 once the exemplars stop naming the
fixture's boundaries, which retroactively shows how much the leak had been
worth. Codex remains the biggest interface turnaround: from removing every note
under the old raw-tool interface (§3.3) to a safe, schema-clean curator under
CurationPlan/1. Across all engines the dominant error is the same: merging the
confusable sibling pairs (Postgres+MySQL → "database", sourdough+pizza →
"baking", running+cycling → "endurance") — a genuine model behavior rather than
prompt non-compliance, since the prompt no longer mentions those pairs. No
engine clears recall and precision ≥0.90 robustly. We report every completed
pass — no run selection.

**Reliability metadata** (all 30 scored passes): no engine ever returned an
empty or unparseable plan, and the executor's validation gate dropped 1 of
2,503 proposed ops — a single haiku op naming a nonexistent slug (99.96 %
gate acceptance). Token usage and per-call cost were not instrumented in this
harness.

**A hidden second fixture, evaluated once — and a warning about the ranking.**
Fixture A was seen repeatedly while the placement prompt evolved, so even with
fixture-disjoint exemplars a test-set-adaptive-tuning risk remains. We
therefore authored **fixture B** (10 domain-disjoint confusable clusters —
telescope observing vs astrophotography, freshwater vs reef aquaria,
bouldering vs rope climbing, plus sewing, beekeeping, fountain pens, chess
endgames — 110 pairs, 12 distractors), froze the prompt and executor *before*
the first run, and ran each engine exactly once, reporting every pass:

| fixture B (110 pairs), single frozen pass | link recall | link precision | distractor links |
|---|---|---|---|
| Claude · sonnet | 1.000 | 0.643 | 0 |
| Claude · haiku | 0.945 | **0.806** | 7 |
| Codex · gpt-5.3-codex-spark | 0.909 | 0.714 | 0 |

The engine ordering **does not transfer**: sonnet's precision advantage on
fixture A (0.85) disappears on B (0.64 — it over-merged sibling clusters,
buying perfect recall), haiku leads precision on B, and only codex is
consistent across both fixtures (0.73/0.71). These are single passes, so B's
per-engine numbers carry no error bars by design (rerunning would reintroduce
selection); the robust conclusions are the ones that survive both fixtures —
placement quality is engine-dependent, sibling-cluster merging is the dominant
error everywhere, safety invariants hold for every engine on both fixtures —
while "which engine curates best" is fixture-sensitive and should be treated
as an open question, not a leaderboard.

### 5.5 Curation at scale on a real vault: structure moves, top-k does not

The fixtures above are synthetic. To test curation on real data — the
reviewer-facing question being whether any of this survives contact with an
actual personal corpus — we ingested the author's working notes (**1,910
Markdown notes, 9.3 MB**, spanning ~20 real projects) into a fresh vault,
froze 40 paraphrase queries against known target notes *before* curation, and
measured retrieval before (A) and after (B) a single `claude/sonnet`
CurationPlan/1 pass. We pre-registered the expectation: rezoning cannot change
BM25 scores, so any retrieval effect must arrive via the link-expansion and
archive paths.

The pass took 85.3 minutes and transformed the vault's *structure*: from one
undifferentiated zone (1,910 notes, 29 links, mean degree 0.02) to **23
project-coherent zones** (220 notes rezoned; the zones recovered the corpus's
actual project boundaries) and **3,485 directed links (mean degree 1.82)**. 271
proposed ops expanded to 1,989 accepted executor actions (dense co-placement
linking); 10 ops were dropped by the safety gates; no note was deleted.

Retrieval, however, barely moved — exactly as pre-registered:

| real vault (n=40 frozen queries) | R@1 | R@5 | R@10 | MRR | R@3+links |
|---|---|---|---|---|---|
| A: raw inbox | 0.10 | 0.20 | 0.300 | 0.146 | 0.200 |
| B: after curation | 0.10 | 0.20 | 0.275 | 0.146 | 0.225 |

Two honest observations. First, **curation is an organizational win, not a
top-k retrieval win**: link-following recovered one additional query (+0.025
on R@3+links) and cost one at R@10 (an archived near-duplicate), leaving BM25
metrics flat. The value of the pass is navigable structure — project zones and
a 120× denser link graph that the agent's digest and link-expansion paths
consume — not reranking. Claims that curation "improves retrieval" should be
read in that light, here and elsewhere. Second, the absolute numbers are far
below LongMemEval's (R@5 0.20 vs 0.97): a real corpus is full of near-duplicate
drafts of the same document, so paraphrase queries have many
lexically-plausible wrong answers and strict single-gold scoring punishes
every near-miss. Session-level benchmarks materially understate how hard
note-level personal retrieval is; we flag this as the honest gap between §5.1
and deployment. (This experiment uses private data; we report aggregates only
and do not release the corpus.)

**Link policy: dense co-placement linking is 4.6× denser than it needs to be.**
Dense reciprocal linking is O(n²) in cluster size, and a reviewer rightly asked
whether it survives real scale. At this vault's scale it does not blow up —
the 3,485 links (3,456 resolve to live notes) arrive per co-placement
*cluster*, not per zone, giving mean degree 1.8, 95th-percentile 17, max 22 —
but most of them turn out to be dead weight. Replaying the *same* placements
under pruned policies (each note keeps only its k lexically most similar
linked neighbors, cosine over stdlib token sets — deterministic, no LLM in the
loop) and re-scoring the frozen-query link-expansion measure:

| link policy (same placements) | directed links | mean deg | p95 | max | R@3+links |
|---|---|---|---|---|---|
| dense reciprocal (current) | 3,456 | 1.81 | 17 | 22 | 0.225 |
| top-k = 3 | 752 | 0.39 | 3 | 3 | **0.225** |
| top-k = 5 | 1,223 | 0.64 | 5 | 5 | 0.225 |
| top-k = 10 | 2,258 | 1.18 | 10 | 10 | 0.225 |
| similarity ≥ median (0.284) | 1,728 | 0.90 | 9 | 18 | 0.200 |

Every top-k policy preserves the entire measured link-expansion benefit —
**k=3 does it with 78 % fewer links** and a human-legible link graph — while
similarity thresholding is the one policy that *loses* the recovered query:
degree capping beats score cutting here. Dense linking is therefore best read
as an upper bound the substrate tolerates at this scale, not a recommendation;
a per-note top-k cap inside co-placement is the natural deployment default.

### 5.6 Curation, live (Morpheus)

Two findings from live nightly passes are worth reporting. First, a
*measurement hazard*: our earliest live run scanned its working directory,
found the benchmark script that had generated its vault, recognized the fixtures
as synthetic, and — following its conservative unattended policy — refused to
curate. A curation agent with workspace visibility can detect the apparatus, so
the harness now isolates the working directory. Second, once isolated, the
labeled suite confirms the safety story end to end: both Claude models resist the
planted prompt-injection canary (mass-archive 0.00, phrase not parroted),
preserve the control and negative-polarity notes, and archive rather than delete
the stale note — matching the code-level guarantees of §5.3. These early live
passes were safety-clean but not accuracy-representative — the haiku pass filed
no inbox notes at all under the then-current prompt; the accuracy numbers in
§5.4 come from the later evolved prompt driven through the harness.

### 5.7 A negative result: passive negative-memory

Birkin renders `polarity: negative` notes into the prompt digest as a "⚠ known
failure — re-verify" annotation, on the hypothesis that an agent that *sees* the
warning avoids the failed path. We tested it directly: with a note recording that
an `ftp` deploy "corrupted the build twice", a decision probe (ftp vs rsync) over
warned / transient-failure / no-memory conditions (haiku, 6 trials each; one
warned trial errored, leaving 5 valid) showed the warning did **not** measurably
change behavior beyond the model's own prior — the baseline already preferred
rsync, and none of the valid warned responses clearly cited the stored failure
as its reason. A rendered negative memory is not self-enforcing;
making it load-bearing needs an active reverify gate in the agent loop, not a
passive annotation (§7).

## 6. Discussion

**Why lexical works here.** Personal memory queries are dominated by named
anchors — project names, people, commands, error strings — exactly the high-idf
tokens BM25 rewards, and LongMemEval's questions share rare content words with
their evidence sessions. Lexical retrieval's classic weakness, paraphrase, is
partially compensated upstream: the nightly curator writes links between related
notes, and retrieval surfaces linked neighbors alongside hits. Where paraphrase
matters more than transparency, an embedding re-ranker can be added over the same
substrate without changing it.

**On baselines and comparability.** §5.1 now carries both a floor (the
substring search the engine replaced) and strong same-harness baselines —
truncated and chunked dense retrieval at two encoder sizes, RRF hybrids with
the fusion constant swept, and a dense reranker, all on the identical
sessions. The lexical engine beats truncated dense, ties chunked dense, and
concedes ~0.02 MRR to the best hybrid (§5.1) — we report that concession
rather than claim a clean sweep. The remaining baseline gap is a
late-interaction (ColBERT-class) retriever, a *frontier* or task-tuned
embedder, and a long-context reader that ingests all sessions without
retrieval. We also note
that cross-system LongMemEval numbers are easy to misread, because retrieval
recall, reranked retrieval, and end-to-end QA accuracy are different metric
categories reported under one benchmark name; we therefore restrict our claim to
*session-level retrieval recall* and do not place it next to any system's
answer-level or hybrid numbers. This caution matters most against MemPalace
[R1], whose reported ~0.966 LongMemEval retrieval band sits in our numeric
range: an independent analysis [23] attributes that band chiefly to verbatim
storage plus ChromaDB's default embedding rather than the palace metaphor —
so the honest cross-read is not "we beat MemPalace" but "the same retrieval
band is reachable with **no embedding model and no vector store at all**,"
which is the zero-dependency point restated. Structured Distillation [24]
reports the opposite lexical result — BM25 degrading — but in a different
regime (heavily *compressed* exchanges, not full notes), consistent with
lexical retrieval depending on the verbatim anchors our vault preserves.

**Accuracy, not latency, is the metric for memory.** CurationPlan/1 makes every
engine safe and comparable, and the hard fixture (§5.4) shows the engines are
not interchangeable on what actually matters: a curator that files correctly
but mis-places notes will under-link and under-retrieve later. Wall-clock is
nearly irrelevant for a once-a-night pass; placement and lifecycle accuracy
compound, because they determine what the system can find tomorrow. The two
jobs are cleanly separable — the deterministic layer guarantees safety and an
auditable diff; model selection maximizes accuracy — which is precisely why
splitting them at the interface is the right design. The §5.4 contamination
episode adds a corollary: when the judge is a prompted model, the prompt is
part of the benchmark surface, and exemplars must be checked against the
fixture the way test data is checked against training data.

## 7. Limitations and future work

No semantic generalization beyond bigram/lexical overlap; single-user,
single-machine assumptions (last-writer-wins sidecars); zone taxonomy seeded by
note type and refined only nightly. Curation accuracy is bounded by model
capability on confusable data (§5.4) and, while now reported at n=10 with
bootstrap CIs, the fixture-B ordering reversal shows per-engine conclusions
are fixture-sensitive — a multi-fixture study with several hidden fixtures,
and running a frontier model to probe the ceiling, remain future work. The
real-vault study (§5.5) is one corpus, one owner, one pass, with frozen
paraphrase queries rather than the owner's natural queries; a **longitudinal
evaluation on real long-lived vaults** — multiple users, 500–5,000 notes each,
over 30–90 days, against no-memory / substring / BM25 / full-Mnemosyne / hybrid
conditions with the user's own natural queries — is still the most important
missing study for the personal-scale claim, and one we cannot run without
deployed users. The end-to-end QA study (§5.1) uses one cheap reader and an oracle
control on two question types; extending the oracle decomposition to all types,
sweeping stronger readers, late-interaction (ColBERT-class) and task-tuned
retrievers, systematically generating
paraphrase and implicit-query variants over the same evidence, and running
LoCoMo [7] all remain open. Decay constants are
argued from the spacing literature, not learned. Finally, §5.7 motivates an
active reverify gate: the open question is whether a hard gate that blocks
reuse of a recorded failed path until the agent cites a verification changes
behavior, and at what false-positive cost.

## 8. Conclusion

For the personal-scale workloads we measured, a memory palace for an LLM agent
does not need a vector database. Files in rooms, an inverted index refreshed by
stat, BM25 with a bigram tokenizer, a forgetting curve the ranking actually
feels, and one offline LLM session a night reach strong session-retrieval
recall on a public benchmark while staying greppable, diffable, and
dependency-free — and, measured in the same harness, a chunked dense
retriever ties this substrate while the best tuned hybrid buys ~0.02 MRR over
it: a real margin, priced at an embedding stack the default deliberately
omits, and one that classic lexical tuning — query-side idf weighting, a
user-turn field, a relative-date prior — buys back to parity (§5.1;
cross-lingual queries remain the case where an embedding re-ranker would earn
its keep).
Extending the same mechanical/judgment split to the curation interface lets
the identical nightly contract run on the Claude and Codex CLIs (and, through
the same one-function contract, any API or local model) and makes even a weak
or adversarial engine unable to violate the vault's file-safety invariants
through that interface — on synthetic fixtures and on a real 1,910-note vault,
where one pass rebuilt the organizational structure while top-k retrieval,
honestly, did not move. Let arithmetic do what arithmetic can, enforce safety
in code, and spend the model only where judgment is genuinely required.

## References

[1] W. Xu et al. *A-MEM: Agentic Memory for LLM Agents.* NeurIPS 2025.
arXiv:2502.12110.
[2] C. Packer et al. *MemGPT: Towards LLMs as Operating Systems.* 2023.
arXiv:2310.08560.
[3] J. S. Park et al. *Generative Agents.* UIST 2023. arXiv:2304.03442.
[4] W. Zhong et al. *MemoryBank.* AAAI 2024. arXiv:2305.10250.
[5] P. Chhikara et al. *Mem0.* 2025. arXiv:2504.19413.
[6] B. Jiménez Gutiérrez et al. *HippoRAG.* NeurIPS 2024. arXiv:2405.14831.
[7] A. Maharana et al. *Evaluating Very Long-Term Conversational Memory (LoCoMo).*
ACL 2024. arXiv:2402.17753.
[8] D. Wu et al. *LongMemEval.* ICLR 2025. arXiv:2410.10813.
[9] P. Rasmussen et al. *Zep: A Temporal Knowledge Graph Architecture for Agent
Memory.* 2025. arXiv:2501.13956.
[10] B. Wang et al. *Self-Controlled Memory (SCM).* DASFAA 2025. arXiv:2304.13343.
[11] K.-H. Lee et al. *ReadAgent.* ICML 2024. arXiv:2402.09727.
[12] S. Robertson and H. Zaragoza. *The Probabilistic Relevance Framework: BM25
and Beyond.* Foundations and Trends in IR 3(4), 2009. doi:10.1561/1500000019.
[13] J. M. J. Murre and J. Dros. *Replication and Analysis of Ebbinghaus'
Forgetting Curve.* PLOS ONE, 2015. doi:10.1371/journal.pone.0120644.
[14] N. J. Cepeda et al. *Distributed Practice in Verbal Recall Tasks.*
Psychological Bulletin 132(3), 2006. PMID 16719566.
[15] Z. Zhang et al. *A Survey on the Memory Mechanism of LLM-based Agents.* 2024.
arXiv:2404.13501.
[16] P. Lewis et al. *Retrieval-Augmented Generation for Knowledge-Intensive NLP
Tasks.* NeurIPS 2020. arXiv:2005.11401.
[17] J. R. Anderson and L. J. Schooler. *Reflections of the Environment in
Memory.* Psychological Science 2(6), 1991.
[18] E. A. Maguire et al. *Routes to Remembering: The Brains Behind Superior
Memory.* Nature Neuroscience 6(1), 2003.
[19] E. Debenedetti et al. *Defeating Prompt Injections by Design (CaMeL).*
2025. arXiv:2503.18813.
[20] A. Jonelagadda, C. Hahn, H. Zheng, and S. Penachio. *Mnemosyne: An
Unsupervised, Human-Inspired Long-Term Memory Architecture for Edge-Based
LLMs.* 2025. arXiv:2510.08601.
[21] A. Nguyen et al. *ByteRover: Agent-Native Memory Through LLM-Curated
Hierarchical Context.* 2026. arXiv:2604.01599.
[22] S. Ji et al. *Infini Memory: Maintainable Topic Documents for Long-Term
LLM Agent Memory.* 2026. arXiv:2606.10677.
[23] R. Dey and P. Viradecha. *Spatial Metaphors for LLM Memory: A Critical
Analysis of the MemPalace Architecture.* 2026. arXiv:2604.21284.
[24] S. Lewis. *Structured Distillation for Personalized Agent Memory: 11x
Token Reduction with Retrieval Preservation.* 2026. arXiv:2603.13017.
[25] Y. Omri et al. *Agent Memory: Characterization and System Implications
of Stateful Long-Horizon Workloads.* 2026. arXiv:2606.06448.
[26] G. Salton and C. Buckley. *Term-Weighting Approaches in Automatic Text
Retrieval.* Information Processing & Management 24(5), 1988. (SMART ltc
query-side idf weighting.)
[27] X. Li and W. B. Croft. *Time-Based Language Models.* CIKM 2003.

**Software and datasets** (repositories fetched 2026-07; to be normalized to
BibTeX `@misc` entries for formal submission):

- [R1] mempalace/mempalace — MIT; verbatim-storage local memory (dynamics, hybrid search).
- [R2] NousResearch/hermes-agent — MIT; self-improving agent, curator lifecycle.
- [R3] letta-ai/letta — Apache-2.0; stateful-agent platform (formerly MemGPT).
- [R4] getzep/graphiti — Apache-2.0; temporal knowledge-graph memory.
- [R5] langchain-ai/langmem — MIT; LangChain long-term-memory SDK.
- [R6] mem0ai/mem0 — Apache-2.0; extraction-based memory layer.
- [R7] topoteretes/cognee — Apache-2.0; self-hosted KG memory platform.
- [D1] xiaowu0162/LongMemEval — MIT; dataset huggingface.co/datasets/xiaowu0162/longmemeval-cleaned.
- [D2] snap-research/locomo — LoCoMo long-term-conversation benchmark.

## Appendix A — Constants

`BM25 k1=1.5 b=0.75 · STRENGTH_STEP=0.25 cap=5.0 · STABILITY_INIT=7d ×1.5 cap=365d
· EFF_FLOOR=0.05 · SPACING_GATE=1h · ZONE_EMA_DECAY=0.9/day · W_DYN=0.3 W_ZONE=0.2
· STALE: eff<0.1 & >90d · ARCHIVE_CAP=max(2, ⌈0.20·active⌉)`

## Appendix B — Reproduction

```bash
pip install -e .                                   # zero runtime deps
python benchmarks/bench.py                         # H1–H5 (offline, seeded)
python benchmarks/bench_longmemeval.py --data <dir>/longmemeval_s_cleaned.json
pip install fastembed numpy                        # benchmark-only, never shipped
python benchmarks/bench_longmemeval_embed.py --data <dir>/longmemeval_s_cleaned.json
python benchmarks/bench_lme_e2e.py --data <dir>/longmemeval_s_cleaned.json --condition top5
python benchmarks/bench_lme_e2e.py --data <dir>/longmemeval_s_cleaned.json --condition oracle
python benchmarks/bench_matrix_local.py --data <dir>/longmemeval_s_cleaned.json  # 2x2, floor, tokenizer
python benchmarks/bench_korean_embed.py            # Korean/mixed vs multilingual-e5
python benchmarks/bench_safety_matrix.py           # defense-layer x attacks
python benchmarks/tune_linkrecall_hard.py --provider claude --model sonnet
python benchmarks/tune_linkrecall_hard.py --provider codex  --model gpt-5.3-codex-spark
python benchmarks/tune_linkrecall_hard.py --provider claude --model sonnet --fixture b  # hidden fixture B (run once)
python benchmarks/bench_dense_strong.py --data <dir>/longmemeval_s_cleaned.json  # chunked/RRF-swept/reranked dense
python benchmarks/sweep2_ranking_v2.py --data <dir>/longmemeval_s_cleaned.json --split full  # tuned lexical stack vs hybrid
python benchmarks/bench_token_cost.py --data <dir>/longmemeval_s_cleaned.json  # context-token cost per strategy
python benchmarks/bench_weight_sensitivity.py     # boost interference grid
python benchmarks/bench_real_vault.py --source <your-notes-dir>  # private corpus; aggregates only
python benchmarks/bench_h4_compliance.py --model haiku --trials 6
birkin curate-memory --provider codex              # real vault; before/after SHA audit
pytest -q                                          # full suite, ≥75% coverage gate
```
