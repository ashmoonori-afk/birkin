"""Per-model presets — senpi-style engine tuning over one shared prompt.

senpi layers model-family system-prompt presets on a dynamic prompt and swaps
tool behavior per family. birkin's equivalent: :func:`resolve` maps a model id
to a preset of

- ``role``   — a short system-prompt overlay (appended by promptgate),
- ``deny_tools`` — tool group/tool names filtered out of the registry,
- ``style``  — work-style hints folded into the role text.

Families, matched by substring on the model id (first hit wins):

  opus   deep-reasoning generalist; full tools; reason before acting
  sonnet balanced default; full tools
  haiku  fast responder; no web/subagent tools; answer first, one tool max
  spark  fast codex worker; plan-only bias; no web/subagent
  gpt    codex engine; emit typed plans / patches, not prose edits
  local  minimal: no tools that assume strong instruction-following

Unknown models get the sonnet (default) preset. Config can override or extend
via ``cfg["model_presets"] = {"substring": {"role": ..., "deny_tools": [...]}}``.
"""

from __future__ import annotations

from typing import Any, Optional

# Strong per-family guidelines (docs/hermes-comparison.md §5). Each is a firm
# directive block — role, tool discipline, output format, verification — not a
# soft hint. The shared birkin prompt stays model-agnostic; this overlay is the
# only place engine behavior diverges.
PRESETS: dict[str, dict[str, Any]] = {
    "opus": {
        "role": (
            "You are running on a deep-reasoning engine. Follow these rules:\n"
            "- ROLE: the deliberate generalist — planning, review, judgment "
            "calls, anything ambiguous or high-stakes.\n"
            "- APPROACH: state your plan in one line before acting on "
            "multi-step tasks; reason first, act second. Prefer one "
            "well-chosen tool call over exploratory chains.\n"
            "- TOOLS: full toolset. Batch independent lookups; never repeat "
            "a call whose answer is already in context.\n"
            "- OUTPUT: thorough where the question warrants it, but lead "
            "with the conclusion; reasoning follows.\n"
            "- VERIFY: before claiming done, re-check the result against the "
            "request (files written? tests run? numbers consistent?)."),
        "deny_tools": [],
    },
    "sonnet": {
        "role": (
            "You are running on a balanced engine. Follow these rules:\n"
            "- ROLE: the everyday driver — conversation, tasks, coding.\n"
            "- APPROACH: act directly; plan aloud only when a task exceeds "
            "~3 steps. Keep tool chains short and purposeful.\n"
            "- TOOLS: full toolset. Read before you write; verify after "
            "you change.\n"
            "- OUTPUT: concise by default; expand only on request or "
            "genuine complexity."),
        "deny_tools": [],
    },
    "haiku": {
        "role": (
            "You are running on a fast, small engine. Follow these rules "
            "STRICTLY:\n"
            "- ROLE: quick answers and single mechanical steps only. If a "
            "task needs planning or multiple edits, say so and stop — do "
            "not attempt it.\n"
            "- APPROACH: answer first from what you know. AT MOST one tool "
            "call per turn, and only when the answer is not already known.\n"
            "- TOOLS: no web, no subagents. Never chain speculative calls.\n"
            "- OUTPUT: 1-5 sentences or a short list. No preamble, no "
            "recap, no hedging."),
        "deny_tools": ["web", "subagent"],
    },
    "spark": {
        "role": (
            "You are running on a fast worker engine. Follow these rules "
            "STRICTLY:\n"
            "- ROLE: a worker, not a conversationalist. Execute exactly the "
            "task given; never expand scope.\n"
            "- APPROACH: no clarifying questions — use stated defaults and "
            "note assumptions in one line at the end if needed.\n"
            "- TOOLS: no web, no subagents.\n"
            "- OUTPUT: ONLY the requested artifact (plan / JSON / patch / "
            "answer). No surrounding prose, no markdown fences unless the "
            "artifact itself is code. Then stop."),
        "deny_tools": ["web", "subagent"],
    },
    "gpt": {
        "role": (
            "You are running on a codex-family engine. Follow these rules:\n"
            "- ROLE: structured execution — code, plans, transformations.\n"
            "- APPROACH: do not ask clarifying questions in unattended "
            "runs; act on best judgment and note assumptions.\n"
            "- TOOLS: no subagents; use your own file/shell tools within "
            "the sandbox you were given.\n"
            "- OUTPUT: typed, structured artifacts (JSON plans, patches, "
            "complete replacement blocks) over free-form prose. When "
            "editing, emit the full new block — never a description of "
            "the edit."),
        "deny_tools": ["subagent"],
    },
    "local": {
        "role": (
            "You are running on a small local engine. Follow these rules "
            "STRICTLY:\n"
            "- ROLE: short factual answers and simple rewrites only.\n"
            "- APPROACH: no tools unless the user explicitly asks for an "
            "action; never guess at tool syntax.\n"
            "- OUTPUT: short, concrete, plain text. If a task is beyond "
            "you, say exactly that in one sentence."),
        "deny_tools": ["web", "subagent"],
    },
}

_FAMILY_ORDER = ("opus", "sonnet", "haiku", "spark", "gpt", "local")

_ALIASES = {  # model-id substring -> family
    "opus": "opus", "sonnet": "sonnet", "haiku": "haiku", "fable": "opus",
    "spark": "spark", "gpt": "gpt", "codex": "gpt",
    "llama": "local", "ollama": "local", "qwen": "local", "mistral": "local",
}


def family_of(model: Optional[str]) -> str:
    m = (model or "").lower()
    for needle, fam in _ALIASES.items():
        if needle in m:
            return fam
    return "sonnet"


def resolve(model: Optional[str],
            cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Preset for ``model``: built-in family preset, then any cfg override
    whose key substring-matches the model id (override wins per field)."""
    preset = dict(PRESETS[family_of(model)])
    m = (model or "").lower()
    for needle, over in ((cfg or {}).get("model_presets") or {}).items():
        if isinstance(over, dict) and needle.lower() in m:
            preset.update({k: v for k, v in over.items() if k in
                           ("role", "deny_tools", "style")})
    return preset


def role_overlay(model: Optional[str],
                 cfg: Optional[dict[str, Any]] = None) -> str:
    role = str(resolve(model, cfg).get("role") or "").strip()
    return f"\n\n## Engine preset\n{role}" if role else ""


def deny_tools(model: Optional[str],
               cfg: Optional[dict[str, Any]] = None) -> set[str]:
    return {str(t) for t in resolve(model, cfg).get("deny_tools") or []}
