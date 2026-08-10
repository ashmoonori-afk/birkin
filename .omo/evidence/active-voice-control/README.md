# Active Voice Control Evidence

This directory contains RED/GREEN test transcripts and real-surface QA
artifacts for `.omo/plans/active-voice-control.md`.

## Plan gate

- Momus attempt: rejected by the harness because its plan gate reported that
  `start-work` had already been invoked.
- First GPT deep fallback: cancelled after four-plus status checks and a
  finish-now steer produced no verdict.
- Bounded GPT ultrabrain fallback: `APPROVE`.

## Baseline design scenario

Command:

```text
npx playwright screenshot --browser chromium --full-page file:///C:/Users/lg/projects/birkin/docs/ironman-voice-agent-workflow-design.html .omo/evidence/active-voice-control/baseline-desktop.png
```

PASS means the command exits 0, the screenshot exists and is non-empty, and
the original source hash remains unchanged.

## Final release receipt

`release-verification.txt` is the current-tree release ledger. It records the
exact full-suite result and coverage, 37 targeted voice/documentation tests,
root-CWD strict Ruff, changed-scope basedpyright, security regressions, Bandit,
dependency audit, real CLI/HTTP/STT/background surfaces, final browser
screenshots, module-size self-review, source preservation, and cleanup.

The scenario-specific RED/GREEN and real-surface receipts remain the detailed
evidence behind that consolidated ledger:

- `red-wake.txt`, `green-wake.txt`, `wake-cli.txt`
- `red-gateway.txt`, `green-gateway.txt`, `gateway-pipeline.txt`
- `red-stt.txt`, `green-stt.txt`, `stt-cli.txt`
- `red-background.txt`, `green-background.txt`, `background-smoke.txt`
- `browser-qa.txt`, `design-desktop.png`, `design-mobile.png`
