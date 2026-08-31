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

from .native_tool_metadata import (
    NATIVE_INSPECT_PARALLEL_TOOLS as NATIVE_INSPECT_PARALLEL_TOOLS,
)

# Backwards-compatible planner name; native posture is declared once in
# native_tool_metadata. load_skill is intentionally not safe because it mutates
# SkillManager state and records usage in the curator ledger.
PARALLEL_SAFE_TOOLS = NATIVE_INSPECT_PARALLEL_TOOLS

# A "parallel" run of one buys nothing but costs a thread.
_MIN_PARALLEL = 2


def _legacy_can_parallelize(name: str) -> bool:
    return name in PARALLEL_SAFE_TOOLS


def is_safe(tool_use: dict[str, Any]) -> bool:
    return tool_use.get("name", "") in PARALLEL_SAFE_TOOLS and isinstance(
        tool_use.get("input", {}) or {}, dict
    )


def plan_segments(
    tool_uses: list[dict[str, Any]],
    can_parallelize: Callable[[str], bool] | None = None,
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Split a batch into contiguous ``("parallel"|"sequential", calls)`` runs.

    ``can_parallelize`` is the trusted classification source when supplied.
    The fallback preserves historic native-name behavior for direct callers
    and registries that predate tool posture classification.

    Emission order is preserved: a run only ever groups calls that were already
    adjacent, so a write between two reads still separates them.
    """
    classify = can_parallelize if callable(can_parallelize) else _legacy_can_parallelize
    segments: list[tuple[str, list[dict[str, Any]]]] = []
    for call in tool_uses:
        tool_input = call.get("input", {}) or {}
        eligible = isinstance(tool_input, dict) and classify(str(call.get("name", "")))
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
