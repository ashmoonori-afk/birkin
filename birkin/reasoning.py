"""Reasoning text: extract it, strip it from visible output, repair histories.

Providers disagree about where a model's thinking lives. DeepSeek/Qwen put it
in ``reasoning``; Moonshot uses ``reasoning_content``; OpenRouter returns a
``reasoning_details`` array; some models emit typed ``thinking`` blocks inside
the content list; and a few leak raw ``<think>`` tags into the visible text.
Without one extractor the text is either silently dropped or shown to the user
as if it were the answer.

Three concerns, one module:

* :func:`extract_reasoning` -- find the thinking, wherever the provider put it.
* :func:`strip_think_blocks` -- remove it from text meant for a human.
* :func:`repair_messages` -- drop assistant turns that were *only* thinking and
  merge the same-role neighbours that dropping creates, so a replayed history
  keeps the user/assistant alternation the APIs require.

Design reference: hermes-agent ``agent/agent_runtime_helpers.py`` (``:55``
tag names, ``:540`` sequence repair, ``:799`` block stripping, ``:1737``
extraction). Reimplemented here against birkin's dict-shaped messages with the
standard library only.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# Tag spellings seen in the wild, including Gemma's ``<thought>`` and the
# scratchpad form some fine-tunes emit.
_TAGS = ("think", "thinking", "reasoning", "REASONING_SCRATCHPAD", "thought")
_ALT = "|".join(_TAGS)

# A complete pair. The backreference keeps ``<think>x</thinking>`` from
# matching; under IGNORECASE it still accepts ``<THINK>x</think>``.
_CLOSED_RE = re.compile(rf"<({_ALT})\b[^>]*>([\s\S]*?)</\1\s*>", re.I)

# An opening tag the provider never closed. Gated to a block boundary (start of
# text, or the beginning of a line) so prose like "use the <think> tag" is not
# swallowed -- the same gate hermes applies in its stream consumer.
_UNTERMINATED_RE = re.compile(rf"(?:^|\n)[ \t]*<(?:{_ALT})\b[^>]*>[\s\S]*$", re.I)


def _blocks(content: Any) -> list[dict[str, Any]]:
    """Content as a block list, whatever shape the caller had."""
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return [{"type": "text", "text": str(content or "")}]


def extract_reasoning(message: Any) -> Optional[str]:
    """Return the message's thinking text, or ``None`` when it has none.

    Structured fields win over inline tags: a provider that reports reasoning
    properly is authoritative, and the inline scan is only a fallback for the
    ones that do not.
    """
    if not isinstance(message, dict):
        return None
    parts: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str):
            text = value.strip()
            if text and text not in parts:
                parts.append(text)

    add(message.get("reasoning"))
    add(message.get("reasoning_content"))
    for detail in message.get("reasoning_details") or []:
        if isinstance(detail, dict):
            add(detail.get("summary") or detail.get("thinking")
                or detail.get("content") or detail.get("text"))
    if parts:
        return "\n\n".join(parts)

    content = message.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                add(block.get("thinking") or block.get("text"))
        if parts:
            return "\n\n".join(parts)
    if isinstance(content, str) and content:
        for match in _CLOSED_RE.finditer(content):
            add(match.group(2))
        if parts:
            return "\n\n".join(parts)
    return None


def strip_think_blocks(content: Any) -> str:
    """Return ``content`` with reasoning tags removed.

    Text that contains no tag is returned unchanged -- not even whitespace is
    touched -- so wiring this into an output path cannot reformat clean replies.
    """
    if not content:
        return ""
    if not isinstance(content, str):
        content = "".join(b.get("text", "") for b in _blocks(content))
    out = _CLOSED_RE.sub("", content)
    out = _UNTERMINATED_RE.sub("", out)
    return content if out == content else out.strip()


def _visible_text(message: dict[str, Any]) -> str:
    return "".join(b.get("text", "") for b in _blocks(message.get("content"))
                   if b.get("type") in (None, "text"))


def _is_thinking_only(message: dict[str, Any]) -> bool:
    """An assistant turn that carries reasoning and nothing else.

    A turn holding a ``tool_use`` block is never thinking-only: its visible text
    is empty by design and dropping it would orphan the matching tool result.
    """
    if message.get("role") != "assistant":
        return False
    for block in _blocks(message.get("content")):
        if block.get("type") not in (None, "text"):
            return False
    return not strip_think_blocks(_visible_text(message)).strip()


def _merge(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Join two same-role messages without mutating either input."""
    a, b = first.get("content"), second.get("content")
    merged: Any
    if isinstance(a, str) and isinstance(b, str):
        merged = f"{a}\n\n{b}" if a and b else (a or b)
    else:
        merged = _blocks(a) + _blocks(b)
    return {**first, **second, "content": merged}


def repair_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a history the chat APIs will accept.

    Drops thinking-only assistant turns, then merges the consecutive same-role
    messages that dropping (or a crash-replayed transcript) leaves behind. The
    input list and its messages are never mutated.
    """
    out: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict) or _is_thinking_only(message):
            continue
        current = dict(message)
        if out and out[-1].get("role") == current.get("role"):
            out[-1] = _merge(out[-1], current)
        else:
            out.append(current)
    return out
