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
