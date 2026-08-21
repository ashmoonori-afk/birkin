"""Run a batch of read-only tool calls concurrently.

A model routinely asks for several independent reads in one turn — fetch three
pages, read four files, search memory two ways. birkin executed them strictly
in sequence, so the turn cost their *sum* even though nothing connected them.
The provider layer already delivers them together (``llm._read_anthropic_stream``
tracks blocks by index precisely so parallel tool_use blocks accumulate
correctly); only the executor was serial.

Only reads are parallelized. Anything that writes — files, shell, memory,
skills, subagents — remains a sequential barrier, which is what makes this safe
without hermes' path-reservation machinery: reads cannot conflict with reads,
and every writer closes the run around it.
"""

from __future__ import annotations

from typing import Any, Callable

# Tools that only read and hold no cross-call state.
#
# load_skill is deliberately ABSENT despite looking like a read: it calls
# reload_if_changed (mutating SkillManager state) and records usage in the
# curator ledger, opening a SQLite connection per call.
PARALLEL_SAFE_TOOLS = frozenset({
    "read_file",
    "list_files",
    "web_fetch",
    "session_search",
    "session_get",
    "memory_search",
    "memory_get_note",
    "memory_related",
})

# A "parallel" run of one buys nothing but costs a thread.
_MIN_PARALLEL = 2


def is_safe(tool_use: dict[str, Any]) -> bool:
    return (tool_use.get("name", "") in PARALLEL_SAFE_TOOLS
            and isinstance(tool_use.get("input", {}) or {}, dict))


def plan_segments(
    tool_uses: list[dict[str, Any]],
    can_parallelize: Callable[[str], bool] | None = None,
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Split a batch into contiguous ``("parallel"|"sequential", calls)`` runs.

    ``can_parallelize`` is the trusted classification source. The default
    preserves the historic native-name behavior for direct callers; runtime
    execution supplies its registry's posture predicate explicitly.

    Emission order is preserved: a run only ever groups calls that were already
    adjacent, so a write between two reads still separates them.
    """
    classify = can_parallelize or (lambda name: name in PARALLEL_SAFE_TOOLS)
    segments: list[tuple[str, list[dict[str, Any]]]] = []
    for call in tool_uses:
        tool_input = call.get("input", {}) or {}
        eligible = (
            isinstance(tool_input, dict)
            and classify(str(call.get("name", "")))
        )
        kind = "parallel" if eligible else "sequential"
        if segments and segments[-1][0] == kind:
            segments[-1][1].append(call)
        else:
            segments.append((kind, [call]))

    # Demote runs too short to be worth a pool, then merge what that leaves
    # adjacent so the caller sees maximal sequential blocks.
    merged: list[tuple[str, list[dict[str, Any]]]] = []
    for kind, calls in segments:
        if kind == "parallel" and len(calls) < _MIN_PARALLEL:
            kind = "sequential"
        if merged and merged[-1][0] == kind == "sequential":
            merged[-1][1].extend(calls)
        else:
            merged.append((kind, calls))
    return merged
