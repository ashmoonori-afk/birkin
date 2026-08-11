"""Guided setup for Birkin's voice-only preferences."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from .. import config, menu
from ..ui import BOLD, CYAN, DIM, GREEN, RESET, YELLOW
from .styles import STYLE_PRESETS, parse_conversation_style
from .wake import WakeConfig

_WAKE_PHRASES = ("Hey Birkin", "Birkin", "I'm home")
_TTS_VOICES = (
    ("coral", "warm and clear"),
    ("sage", "calm and grounded"),
    ("verse", "bright and expressive"),
    ("onyx", "deep and steady"),
)


def is_complete() -> bool:
    cfg = cast("dict[str, object]", config.load_config())
    values = cfg.get("voice", {})
    return (
        isinstance(values, Mapping)
        and cast("Mapping[str, object]", values).get(
            "onboarding_complete"
        ) is True
    )


def _select_wake_phrase(current: str, *, complete: bool) -> str | None:
    labels = [f'"{phrase}"' for phrase in _WAKE_PHRASES]
    labels.append("Custom phrase…")
    default = (
        _WAKE_PHRASES.index(current)
        if complete and current in _WAKE_PHRASES
        else len(_WAKE_PHRASES) if complete else 0
    )
    choice = menu.select(
        f"{BOLD}1 · What should wake me?{RESET}",
        labels,
        default=default,
    )
    if choice is None:
        return None
    if choice < len(_WAKE_PHRASES):
        return _WAKE_PHRASES[choice]

    while True:
        try:
            entered = input(f"Custom wake phrase [{current}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        wake_phrase = entered or current
        try:
            _ = WakeConfig(wake_phrase=wake_phrase)
        except ValueError:
            print(
                f"{YELLOW}Use at least one letter or number so speech "
                + f"recognition has something to match.{RESET}"
            )
            continue
        return wake_phrase


def _select_style(current: str) -> str | None:
    labels = [
        f"{preset.label} — {preset.description}"
        for preset in STYLE_PRESETS
    ]
    keys = [preset.key for preset in STYLE_PRESETS]
    default = keys.index(current) if current in keys else 0
    choice = menu.select(
        f"\n{BOLD}2 · How should our conversations feel?{RESET}",
        labels,
        default=default,
    )
    return None if choice is None else keys[choice]


def _select_voice(current: str) -> str | None:
    voices = list(_TTS_VOICES)
    if current not in {voice for voice, _description in voices}:
        voices.insert(0, (current, "current voice"))
    labels = [
        f"{voice.title()} — {description}"
        for voice, description in voices
    ]
    keys = [voice for voice, _description in voices]
    choice = menu.select(
        f"\n{BOLD}3 · Choose a voice{RESET}",
        labels,
        default=keys.index(current),
    )
    return None if choice is None else keys[choice]


def run() -> int:
    cfg = cast("dict[str, object]", config.load_config())
    stored = cfg.get("voice", {})
    voice: dict[str, object] = (
        dict(cast("Mapping[str, object]", stored))
        if isinstance(stored, Mapping)
        else {}
    )
    complete = voice.get("onboarding_complete") is True
    current_wake = str(voice.get("wake_phrase") or "Hey Birkin")
    current_style = parse_conversation_style(
        voice.get("conversation_style", "")
    )
    current_voice = str(voice.get("tts_voice") or "coral")

    print(f"\n{CYAN}{BOLD}Voice setup{RESET}")
    print(
        f"{DIM}Three quick choices, then we can start talking. "
        + f"Enter keeps the highlighted choice.{RESET}\n"
    )

    wake_phrase = _select_wake_phrase(current_wake, complete=complete)
    if wake_phrase is None:
        print(f"\n{DIM}Voice setup cancelled; nothing was changed.{RESET}")
        return 1
    conversation_style = _select_style(current_style)
    if conversation_style is None:
        print(f"\n{DIM}Voice setup cancelled; nothing was changed.{RESET}")
        return 1
    tts_voice = _select_voice(current_voice)
    if tts_voice is None:
        print(f"\n{DIM}Voice setup cancelled; nothing was changed.{RESET}")
        return 1

    voice.update(
        {
            "wake_phrase": wake_phrase,
            "conversation_style": conversation_style,
            "tts_voice": tts_voice,
            "onboarding_complete": True,
        }
    )
    cfg["voice"] = voice
    path = config.save_config(cfg)

    style = next(
        preset
        for preset in STYLE_PRESETS
        if preset.key == conversation_style
    )
    print(f"\n{GREEN}{BOLD}I'm here.{RESET}")
    print(f"  Wake phrase  {CYAN}{wake_phrase}{RESET}")
    print(f"  Style        {CYAN}{style.label}{RESET}")
    print(f"  Voice        {CYAN}{tts_voice.title()}{RESET}")
    print(f"\n{DIM}Saved to {path}")
    print(f"Run `birkin voice setup` whenever you want to change this.{RESET}")
    return 0
