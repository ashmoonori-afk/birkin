---
name: active-voice-control
producer: ulw-plan
intent: clear
review_required: true
status: approved-for-execution
worktree: C:/Users/lg/Documents/Claude/Projects/Birkin/active-voice-control
branch: active-voice-control
tier: HEAVY
---

# Active Voice Control

## Goal

Ship and push a tested Birkin voice-control path that detects a clap plus the
configured wake phrase, routes the following command through the existing
Gateway and its approval boundary, speaks the response with OpenAI TTS, and
can enqueue long work into a bounded background broker with durable receipts.
Replace the supplied standalone HTML with the implementation-accurate design
and update both README languages.

Git cannot represent the requested name with spaces, so the branch is
`active-voice-control`. The user's untracked source HTML in
`C:/Users/lg/projects/birkin` must remain untouched; branch work copies it into
this isolated worktree.

## Decisions

### Voice stack

- Make `openai[realtime,voice_helpers]>=2.53,<3` a normal runtime dependency.
  The user explicitly retired the zero-runtime-dependency policy.
- Use the official open-source `openai-python` SDK, not the OpenAI Agents SDK
  `VoicePipeline`, for the first implementation. This keeps current model
  contracts explicit and preserves Birkin as the only agent loop.
- Live STT: `gpt-live-transcribe` over a Realtime transcription WebSocket with
  mono PCM16 at 24 kHz.
- Bounded-file STT: `gpt-transcribe` through `/v1/audio/transcriptions`.
- TTS: `gpt-4o-mini-tts`, voice configurable with default `coral`, streamed
  as PCM16/24 kHz.
- `gpt-realtime-2.1` remains a documented future conversational mode. It must
  not silently replace `Gateway.handle()` or Birkin approvals.
- Codex remains a possible text-reasoning provider behind the Gateway. Codex
  OAuth is not reused as an Audio API credential; voice requires
  `OPENAI_API_KEY`.

Official sources:

- https://developers.openai.com/api/docs/guides/voice-agents
- https://developers.openai.com/api/docs/guides/realtime-transcription
- https://developers.openai.com/api/docs/guides/speech-to-text
- https://developers.openai.com/api/docs/guides/text-to-speech
- https://developers.openai.com/api/docs/guides/realtime
- https://github.com/openai/openai-python/blob/main/pyproject.toml
- https://developers.openai.com/codex/auth

### Trust and privacy

- A wake phrase is a routing trigger, never authorization.
- The local HTTP endpoint accepts only `http` or `voice` as an explicit
  channel value. It must reject attempts to spoof `telegram` or unknown
  channels.
- `Gateway.handle("voice", ...)` remains untrusted under the existing
  `trusted_telegram = channel == "telegram" and ...` rule in
  `birkin/gateway/core.py:659-663`; voice never sets approved-work state.
- Keep `BIRKIN_HTTP_TOKEN` behavior unchanged and forward the token only from
  the environment.
- Raw microphone audio stays in memory; no raw audio file is written by the
  live path.
- Do not log API keys, raw audio, or full transcripts. TTS documentation must
  disclose that the output is AI-generated.

## Architecture

```text
sounddevice mono PCM16/24kHz
  -> birkin.voice.wake.ClapPhraseGate
  -> OpenAI live/file transcription adapter
  -> immediate local state: WAKE_ACCEPTED + ack
  -> birkin.voice.gateway.GatewayClient
  -> POST /message {"channel":"voice","session":...,"text":...}
  -> LocalHTTPChannel -> Gateway.handle("voice", ...)
  -> foreground reply OR BackgroundBroker job receipt
  -> OpenAI streaming gpt-4o-mini-tts
  -> sounddevice speaker or deterministic file/stdout sink
```

### Module contracts

- `birkin/voice/config.py`: frozen `VoiceConfig` parsed once from the merged
  config. It owns model names, wake settings, Gateway URL/session, sample rate,
  capture windows, TTS voice, background cap, and receipt directory.
- `birkin/voice/audio.py`: WAV/PCM loading and live `sounddevice` capture/play.
  Hardware imports are lazy so `--help` and deterministic tests do not open a
  device.
- `birkin/voice/wake.py`: normalize phrases with Unicode NFKC, case-folding,
  punctuation removal, and collapsed whitespace. A clap is a 20 ms frame whose
  absolute peak exceeds the configured floor and whose crest factor
  `peak / max(rms, epsilon)` exceeds the configured ratio. `WakeGate.evaluate`
  accepts only clap plus exact normalized phrase and enforces cooldown through
  an injected monotonic clock.
- `birkin/voice/openai_voice.py`: current OpenAI REST/Realtime contracts,
  bounded input validation, no credential persistence, and injectable client
  seams. Test fakes must return real-shaped transcript/audio data.
- `birkin/voice/gateway.py`: local JSON POST client. It always submits
  `channel="voice"` and never accepts an arbitrary caller-supplied trust
  channel.
- `birkin/voice/controller.py`: one-turn state machine:
  capture/load wake audio -> transcribe/provided transcript -> gate -> emit
  ACK -> get/provided command -> foreground or background route -> TTS/sink.
- `birkin/background.py`: bounded `ThreadPoolExecutor`, immutable job snapshots,
  statuses `queued|running|succeeded|failed|cancelled`, ordered progress events,
  cancellation of queued jobs, JSON receipt per transition, and explicit
  `close()`. No sleeps or polling.
- `birkin/cli.py`: `birkin voice` with `--once`, `--audio`, `--transcript`,
  `--command`, `--background`, `--gateway-url`, `--tts-output`, and
  `--no-playback`. Deterministic fixture mode must not require API credentials.

Each new pure Python module stays below 250 LOC. Provider, wake, Gateway, and
broker boundaries use typed protocols/dataclasses; no `Any` leaks into internal
contracts.

## Success scenarios

### S1 Wake

- RED: `uv run pytest tests/test_voice_wake.py -q` fails because the new wake
  contract is absent, not because of syntax/import errors in the test.
- GREEN: the same command passes clap+phrase, clap-only, phrase-only, malformed
  phrase, Unicode/case normalization, and injected-clock cooldown cases.
- Surface happy:
  `uv run birkin voice --once --audio tests/fixtures/voice/clap_then_phrase.wav --transcript "Daddy is home" --command "status"`
  exits 0 and prints `WAKE_ACCEPTED` and `COMMAND=status`.
- Surface edge:
  `uv run birkin voice --once --audio tests/fixtures/voice/phrase_only.wav --transcript "Daddy is home" --command "status"`
  exits nonzero and prints `WAKE_REJECTED`.

The WAV files are QA runtime fixtures generated deterministically by
`script/qa/generate_voice_fixtures.py`; the cleanup todo removes them after the
captured scenario.

### S2 Gateway and TTS

- RED/GREEN: `uv run pytest tests/test_gateway_voice.py -q`.
- The local HTTP integration test and QA driver start `LocalHTTPChannel(0)`,
  send literal JSON with `channel=voice`, and prove the fake Gateway received
  `("voice", fixed-session, command)`.
- A local OpenAI-compatible fake endpoint captures the TTS request and returns
  deterministic PCM bytes; the configured sink receives the bytes.
- `telegram` and unknown channel values return HTTP 400.

### S3 Background and safety

- RED/GREEN:
  `uv run pytest tests/test_background_broker.py tests/test_voice_security.py -q`.
- No fixed sleeps: tests subscribe with `threading.Event` before enqueue and
  release exact state transitions under bounded timeouts.
- `uv run python script/qa/voice_background_smoke.py` prints:
  `FOREGROUND_ACK=PASS`, `BACKGROUND_RECEIPT=PASS`, and
  `VOICE_APPROVAL_BYPASS=PASS`.
- The driver owns a temp `BIRKIN_HOME`, ephemeral port, broker, and server
  thread, then closes/removes each and prints a cleanup receipt.

### S4 Design and docs

- Copy the user's source HTML, then replace obsolete local-model and
  zero-dependency claims with the shipped OpenAI chain, decision table, file
  map, atomic implementation plan, trust boundaries, exact commands, and
  implementation status.
- Update `docs/DESIGN.md`, `README.md`, and `README.ko.md` so no published
  zero-dependency claim contradicts `pyproject.toml`.
- Capture fresh desktop and mobile Playwright screenshots of the standalone
  file, with action log and zero console/page errors.

### S5 Release

- Changed-file LSP diagnostics: zero errors.
- Targeted tests, `uv run pytest -q`, ruff, basedpyright, security regressions,
  Bandit, and dependency audit pass, or a pre-existing/unavailable check is
  identified with exact evidence and the next-best check.
- Manual CLI: `--help`, happy wake, rejected wake/invalid input.
- Plan review and final review have no criterion-blocking concern.
- Atomic commits follow repository history and include
  `Plan: .omo/plans/active-voice-control.md`.
- `git status --short` is clean and
  `git ls-remote --heads origin active-voice-control` equals local HEAD.

## Delegation topology

- Completed `deep` librarian lane: official OpenAI model/API/SDK research.
- Closed inconclusive Claude lanes: provider quota prevented output; no result
  from those lanes is treated as evidence.
- Closed inconclusive `ultrabrain` contract lane after four checks and two
  finish-now steers; root verified the needed contracts directly.
- Root keeps all production edits because the modules share CLI/config/HTTP
  contracts and sequential RED→GREEN evidence. Independent final visual and
  plan reviews go to read-only reviewer children.

## Todos

- [x] 17. Momus plan review: approve contracts before implementation
  - Recommended task executor category: `unspecified-high`
  - Verify: reviewer returns no success-criterion blocker.
- [x] 18. `tests/test_openai_voice.py`: capture STT contract RED
  - Recommended task executor category: `unspecified-high`
  - Verify: failure identifies missing GPT STT and microphone contracts.
- [x] 19. OpenAI STT and microphone: implement collection GREEN
  - Recommended task executor category: `deep`
  - Verify: recorded/in-memory STT and injected microphone tests pass.
- [x] 20. CLI STT surface: capture command collection evidence
  - Recommended task executor category: `unspecified-high`
  - Verify: fake OpenAI API collects wake phrase and command from audio.
- [x] 1. `docs/` and `.omo/`: preserve source and capture baseline design
  - Recommended task executor category: `quick`
  - Verify: source main-worktree bytes remain unchanged; baseline screenshot exists.
- [x] 2. `tests/test_voice_wake.py`: add wake contract and capture RED
  - Recommended task executor category: `unspecified-high`
  - Verify: failure names missing wake behavior, not a malformed test.
- [x] 3. `pyproject.toml`, config, `birkin/voice/`, CLI: implement wake slice
  - Recommended task executor category: `deep`
  - Verify: S1 test GREEN and no module exceeds 250 pure LOC.
- [x] 4. CLI fixture scenarios: capture happy and rejection evidence
  - Recommended task executor category: `unspecified-low`
  - Verify: exact exit codes/sentinel lines and fixture cleanup receipt.
- [x] 5. Git: commit verified wake increment
  - Recommended task executor category: `quick`
  - Verify: commit tests green and message/history convention matches.
- [x] 6. `tests/test_gateway_voice.py`: add pipeline contract and capture RED
  - Recommended task executor category: `unspecified-high`
  - Verify: failure identifies absent channel/provider behavior.
- [x] 7. HTTP and OpenAI adapters: implement Gateway/TTS pipeline
  - Recommended task executor category: `deep`
  - Verify: S2 tests GREEN; spoofed trust channels remain rejected.
- [x] 8. Live HTTP/CLI driver: capture pipeline evidence and cleanup
  - Recommended task executor category: `unspecified-high`
  - Verify: literal request/reply/audio artifact plus server teardown.
- [x] 9. Git: commit verified Gateway/TTS increment
  - Recommended task executor category: `quick`
  - Verify: commit is atomic and green.
- [x] 10. Broker/security tests: capture background and safety RED
  - Recommended task executor category: `ultrabrain`
  - Verify: failures identify missing broker/security contracts.
- [x] 11. `birkin/background.py` and controller: implement mission slice
  - Recommended task executor category: `ultrabrain`
  - Verify: S3 tests GREEN with event-driven concurrency.
- [x] 12. Background smoke driver: capture PASS and cleanup evidence
  - Recommended task executor category: `unspecified-high`
  - Verify: all three PASS sentinels and no live resources remain.
- [x] 13. Git: commit verified background/safety increment
  - Recommended task executor category: `quick`
  - Verify: commit is atomic and green.
- [x] 14. HTML, DESIGN, README files: publish researched implementation
  - Recommended task executor category: `writing`
  - Verify: code/config/commands/source URLs cross-check in both languages.
- [x] 15. Browser visual QA: capture desktop/mobile and reviewer verdicts
  - Recommended task executor category: `visual-engineering`
  - Verify: fresh complete screenshots, zero errors, CJK/layout PASS, cleanup.
- [x] 16. Git: commit verified design and documentation increment
  - Recommended task executor category: `quick`
  - Verify: shipped docs match current code exactly.

## Final verification wave

- [x] F1. Diagnostics and targeted tests: prove changed-code correctness
  - Recommended task executor category: `unspecified-high`
  - Verify: LSP errors 0 and every targeted command GREEN.
- [x] F2. Full suite and static checks: prove regression safety
  - Recommended task executor category: `unspecified-high`
  - Verify: pytest, ruff, basedpyright, Bandit, dependency audit results captured.
- [x] F3. CLI and browser surfaces: replay every success scenario
  - Recommended task executor category: `unspecified-high`
  - Verify: exact commands/screenshots all PASS and cleanup receipts exist.
- [x] F4. Momus and self-review: approve criteria and code quality
  - Recommended task executor category: `unspecified-high`
  - Verify: no criterion blocker; spaghetti/docs/security checks recorded.
- [x] F5. Final commit and push: publish verified clean branch
  - Recommended task executor category: `quick`
  - Verify: clean status and remote branch HEAD equals local HEAD.

## Must not have

- No wake phrase treated as approval or authentication.
- No raw audio, transcript, or API key persisted by default.
- No browser-exposed standard API key.
- No silent fallback to local STT/TTS models.
- No second text-agent loop inside the voice sidecar.
- No fixed sleeps/polling in tests.
- No unrelated refactor, formatting churn, or edits to the user's original
  untracked HTML in the main worktree.
