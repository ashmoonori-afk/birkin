"""Persona ("SOUL") layer — birkin's editable personality.

Mirrors hermes-agent's SOUL.md mechanism (NousResearch/hermes-agent, MIT; the
tone language below is adapted from its docs and ``cli-config.yaml.example``
``agent.personalities`` presets): a plain markdown file the user owns and edits.

In the **REPL** it is read fresh on every turn (see :mod:`birkin.runtime`), so
edits take effect with no restart. The **persistent gateway** snapshots it into
the warm Claude session's system prompt when that session starts, so editing
``SOUL.md`` (or ``/personality``) applies to an existing warm conversation only
after ``/new`` (or the next gateway start). When ``SOUL.md`` is present and
non-empty its contents are injected verbatim as birkin's identity; otherwise the
built-in default voice in :mod:`birkin.prompts` is used.

Pure standard library — no third-party dependencies.
"""

from __future__ import annotations

from pathlib import Path

from . import config

# The persona seeded on first run. Warm but honest — never sycophantic.
DEFAULT_SOUL = """\
# birkin's persona

You are a warm, encouraging companion who is also a rigorous expert.

## Voice
- Friendly and conversational; greet people and react like a real person would.
- Direct without being cold; kind without being fake or sycophantic.
- Concise by default; go deeper only when it actually helps.

## With the user
- Use their name and what you remember about them to make replies feel personal.
- When they seem stuck or frustrated, acknowledge it before diving into the fix.
"""

# Swappable tone presets (`/personality <name>`). Adapted from
# NousResearch/hermes-agent (MIT) cli-config.yaml.example `agent.personalities`.
PRESETS: dict[str, str] = {
    "warm": DEFAULT_SOUL,
    "concise": (
        "# birkin's persona\n\n"
        "You are a concise assistant. Keep responses brief and to the point. "
        "Warm but efficient — answer first, elaborate only if asked.\n"
    ),
    "mentor": (
        "# birkin's persona\n\n"
        "You are a patient teacher. Explain concepts clearly with small "
        "examples, check understanding, and encourage. Never condescend.\n"
    ),
    "direct": (
        "# birkin's persona\n\n"
        "You are a pragmatic expert with strong taste. Be direct without being "
        "cold, push back when something is a bad idea, admit uncertainty "
        "plainly, and skip politeness theater.\n"
    ),
}


def soul_path() -> Path:
    """Location of the user-editable persona file (``<birkin_home>/SOUL.md``)."""
    return config.birkin_home() / "SOUL.md"


def read_soul() -> str:
    """Return the persona text, or "" when no SOUL.md exists / is empty."""
    path = soul_path()
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_soul(text: str) -> Path:
    """Write ``text`` as the persona, normalising the trailing newline.

    Uses a temp-file + atomic replace so an interrupted write can't leave a
    half-written SOUL.md (which ``read_soul`` would silently treat as empty).
    """
    path = soul_path()
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text.rstrip() + "\n", encoding="utf-8")
        tmp.replace(path)  # atomic on POSIX; same-dir replace on Windows
    except OSError:
        try:  # don't leave a partial .tmp behind (Windows replace can fail)
            tmp.unlink()
        except OSError:
            pass
        raise
    return path


def promote_guidance(guidance: str) -> Path:
    """Append approved mask guidance into SOUL.md idempotently."""
    content = guidance.strip()
    path = soul_path()
    if not content:
        return path
    existing = ""
    if path.is_file():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            existing = ""
    if content in existing:
        return path
    prefix = existing.rstrip()
    addition = "## Promoted guidance\n" + content
    merged = f"{prefix}\n\n{addition}" if prefix else addition
    return write_soul(merged)


def seed_default(force: bool = False) -> bool:
    """Create SOUL.md with the default persona if it is missing.

    Returns ``True`` when a file was written, ``False`` when one already existed
    (and ``force`` was not set).
    """
    path = soul_path()
    if path.exists() and not force:
        return False
    write_soul(DEFAULT_SOUL)
    return True
