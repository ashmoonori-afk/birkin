"""OODA loop contract: make repeated failure visible and force reorientation.

The agent loop (Observe-Orient-Decide-Act) has a silent failure mode: the model
retries the *same* tool call with the *same* arguments after an error, burning
turns without ever re-orienting. This module detects that pattern
deterministically - no LLM call - and hands the loop a short ASCII nudge to
inject once per stall episode.

- :class:`StepRecord` is one observed tool outcome (tool name, a digest of the
  canonicalized arguments, success flag, timestamp).
- :class:`OodaTracker` keeps the recent step window and answers ``stalled()``:
  the same (tool, args_digest) failing >= ``repeats`` times within the window.
  ``reorient_note()`` is the model-facing text; ``acknowledge()`` clears the
  current episode so the note is single-shot until a *new* stall forms.

Everything here is fail-open: the tracker never raises on its own logic, and
callers wrap recording/injection so a tracker exception cannot break a turn.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

DEFAULT_STALL_REPEATS = 3
# How many recent steps the stall scan considers. Generous on purpose: a stall
# should still register when the model interleaves a couple of other probes.
DEFAULT_WINDOW = 50


def args_digest(args: Any) -> str:
    """Stable sha1 of a tool-call argument mapping.

    Canonicalized via ``json.dumps(sort_keys=True)`` so key order and
    insignificant whitespace never change the digest. Non-JSON-serializable
    values fall back to ``repr`` -- the digest only has to be *stable*, not
    pretty.
    """
    if not isinstance(args, dict):
        args = {} if args is None else {"_": args}
    try:
        canonical = json.dumps(args, sort_keys=True, separators=(",", ":"),
                               default=repr)
    except (TypeError, ValueError):
        canonical = repr(sorted(args.items(), key=lambda kv: str(kv[0])))
    return hashlib.sha1(  # nosec B324 -- dedup key, not a security digest
        canonical.encode("utf-8", "replace"), usedforsecurity=False
    ).hexdigest()


@dataclass
class StepRecord:
    tool: str
    args_digest: str
    ok: bool
    ts: float


class OodaTracker:
    """Windowed record of tool outcomes with stall detection."""

    def __init__(self, *, repeats: int = DEFAULT_STALL_REPEATS,
                 window: int = DEFAULT_WINDOW,
                 enabled: bool = True) -> None:
        self.repeats = max(2, int(repeats))
        self.window = max(self.repeats, int(window))
        self.enabled = bool(enabled)
        self.steps: list[StepRecord] = []
        self._stalled_key: tuple[str, str] | None = None

    def reset(self) -> None:
        self.steps = []
        self._stalled_key = None

    def record(self, tool: str, args: Any, ok: bool) -> StepRecord | None:
        """Append one observed outcome. Returns the record (None when disabled)."""
        if not self.enabled:
            return None
        rec = StepRecord(tool=str(tool), args_digest=args_digest(args),
                         ok=bool(ok), ts=time.time())
        self.steps.append(rec)
        if len(self.steps) > self.window:
            del self.steps[: len(self.steps) - self.window]
        if rec.ok:
            # A success on this exact action breaks its stall episode; a new
            # one can still form on later failures.
            if self._stalled_key == (rec.tool, rec.args_digest):
                self._stalled_key = None
        return rec

    def _streak(self) -> tuple[tuple[str, str] | None, int]:
        """(key, consecutive failures) of the trailing identical-action run."""
        key: tuple[str, str] | None = None
        count = 0
        for rec in reversed(self.steps):
            k = (rec.tool, rec.args_digest)
            if key is None:
                if rec.ok:
                    break
                key = k
            if k != key or rec.ok:
                break
            count += 1
        return key, count

    def stalled(self) -> bool:
        """True when one identical action is failing on repeat right now."""
        if not self.enabled:
            return False
        key, count = self._streak()
        if key is not None and count >= self.repeats:
            self._stalled_key = key
            return True
        return False

    def stall_info(self) -> dict[str, Any]:
        """Small event payload describing the current stall (empty when none)."""
        key, count = self._streak()
        if key is None or count < self.repeats:
            return {}
        return {"tool": key[0], "args_digest": key[1], "failures": count}

    def reorient_note(self) -> str:
        """The single-shot injection text; empty string when nothing is stalled.

        ASCII-only and model-facing: it asks for a hypothesis, it does not
        prescribe a fix.
        """
        info = self.stall_info()
        if not info:
            return ""
        return (
            "[birkin ooda] Stall detected: tool "
            f"'{info['tool']}' has failed {info['failures']} times in a row "
            "with identical arguments. Before retrying it, state your "
            "hypothesis for WHY it failed and what you changed, or choose a "
            "different probe to observe the problem from another angle."
        )

    def acknowledge(self) -> None:
        """Clear the current stall episode after its note was injected."""
        self._stalled_key = None
        steps = self.steps
        if steps:
            # Break the trailing run so the same episode cannot re-fire on the
            # very next identical failure; a full new streak still can.
            last = steps[-1]
            steps[-1] = StepRecord(last.tool, last.args_digest, True, last.ts)
