"""Cynefin routing -- what shape of work is this turn asking for?

A one-line question and a multi-system refactor used to reach the model as
the same shape of turn, so simple asks got over-planned and hard asks got
answered off the cuff. This module classifies the user text into a Cynefin
domain -- clear / complicated / complex / chaotic -- and turns the domain
into a short execution-strategy nudge for the warm-turn context.

Deterministic and prompt-only: ``classify`` is a lexical heuristic (no LLM
call), and ``strategy_note`` is an ASCII note appended by promptgate behind
``cynefin_enabled``. A wrong domain costs one slightly-off nudge, which is
why the heuristic is allowed to stay simple. (.plans/thinking-frameworks.md
item 1)

Pure standard library.
"""

from __future__ import annotations

import re

DOMAINS = ("clear", "complicated", "complex", "chaotic")

# A pasted failure is its own domain: stabilize before building anything.
_ERROR_RE = re.compile(
    r"(traceback|exception\b|error[:\s]|stack ?trace|segfault|panic\b"
    r"|crash|core dump"
    r"|\uc5d0\ub7ec|\uc624\ub958|\ubc84\uadf8|\uc7a5\uc560"
    r"|\uc548 ?\ub3fc|\uc548 ?\ub428|\uc548 ?\ub429\ub2c8\ub2e4"
    r"|\uc8fd\uc5c8|\uae68\uc84c|\uc2e4\ud328)",
    re.IGNORECASE)

# More than one goal in a sentence is the complexity signal that length alone
# misses ("A and then B", Korean "-\ud558\uace0 ... \uadf8\ub9ac\uace0 ...").
_MULTI_GOAL_RE = re.compile(
    r"(\band then\b|\balso\b|\bafter that\b|\bas well as\b|\bplus\b|;"
    r"|\uadf8\ub9ac\uace0|\uadf8 ?\ub2e4\uc74c|\ub2e4\uc74c\uc5d0\ub294?"
    r"|\ub610\ud55c?|\ud558\uace0 \ub098\uc11c|\ub458 ?\ub2e4"
    r"|\ubaa8\ub450|\uc804\ubd80|\uac01\uac01)",
    re.IGNORECASE)

_IMPERATIVE_RE = re.compile(
    r"(\b(add|build|implement|create|fix|refactor|write|make|delete|remove"
    r"|rename|migrate|deploy|integrate|install|update|test|design|clean)\b"
    r"|\ud574\uc918|\ud574\ub77c|\ud558\uc790|\ub9cc\ub4e4\uc5b4"
    r"|\ucd94\uac00\ud574|\uace0\uccd0|\uc218\uc815\ud574|\uc0ad\uc81c\ud574"
    r"|\ubc14\uafd4|\uad6c\ud604\ud574|\ub9ac\ud329\ud130|\ubc30\ud3ec\ud574"
    r"|\ud1b5\ud569\ud574|\uc124\uce58\ud574|\ud14c\uc2a4\ud2b8\ud574"
    r"|\uc9c0\uc6cc|\uc815\ub9ac\ud574)",
    re.IGNORECASE)

_QUESTION_RE = re.compile(
    r"(\?|^\s*(what|why|how|when|where|which|who|is|are|does|do|can|could"
    r"|should|explain)\b"
    r"|\ubb50\uc57c|\ubb50\uc608\uc694|\ubb34\uc5c7|\uc5b4\ub5bb\uac8c"
    r"|\uc65c\b|\uc5b8\uc81c|\uc5b4\ub514|\ub204\uad6c|\uc778\uac00\uc694"
    r"|\uc77c\uae4c|\uc54c\ub824\uc918|\uc124\uba85\ud574)",
    re.IGNORECASE)

# ASCII-only, <= 6 lines each: these strings reach CLI output on cp1252.
_NOTES = {
    "clear": (
        "Cynefin domain: CLEAR.\n"
        "Answer directly with minimal tool calls.\n"
        "Do not decompose or over-plan a simple request."),
    "complicated": (
        "Cynefin domain: COMPLICATED.\n"
        "List the steps first, then execute them in order.\n"
        "Verify each step before moving to the next."),
    "complex": (
        "Cynefin domain: COMPLEX.\n"
        "Decompose into independently verifiable sub-tasks first.\n"
        "Use an issue tree or the hard-task workflow; verify each part.\n"
        "Expect the plan to change as results come back."),
    "chaotic": (
        "Cynefin domain: CHAOTIC.\n"
        "Stabilize first: reproduce the failure with the smallest safe probe.\n"
        "Make no bulk edits until the failure is understood."),
}


def classify(text: str, *, recent_failures: int = 0) -> str:
    """Map user text to a Cynefin domain. Deterministic; never raises."""
    t = (text or "").strip()
    if not t:
        return "clear"
    if recent_failures >= 2 or _ERROR_RE.search(t):
        return "chaotic"
    imperatives = len(_IMPERATIVE_RE.findall(t))
    multi_goals = len(_MULTI_GOAL_RE.findall(t))
    long_form = len(t) >= 400
    if (imperatives >= 2 and multi_goals >= 1) \
            or (long_form and imperatives >= 1) \
            or multi_goals >= 3:
        return "complex"
    # "explain X" / "설명해줘" reads as an imperative but asks for an answer,
    # not for work: a lone question outranks a lone imperative marker.
    if _QUESTION_RE.search(t) and imperatives <= 1 and multi_goals == 0 \
            and not long_form:
        return "clear"
    if imperatives >= 1:
        return "complicated"
    return "clear"


def strategy_note(domain: str) -> str:
    """The ASCII execution nudge for ``domain``; empty for unknown input."""
    return _NOTES.get(domain, "")


def note_for(text: str, *, recent_failures: int = 0) -> str:
    """Classify and render in one call -- the promptgate entry point."""
    return strategy_note(classify(text, recent_failures=recent_failures))
