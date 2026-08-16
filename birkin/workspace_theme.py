"""Birkin semantic theme roles shared by terminal and web surfaces."""

from __future__ import annotations

import math

ROLES = (
    "accent",
    "border",
    "border_accent",
    "border_muted",
    "text",
    "muted",
    "dim",
    "background",
    "surface",
    "surface_raised",
    "focus_ring",
    "success",
    "warning",
    "error",
    "info",
    "pending",
    "blocked",
    "action_needed",
    "selected_bg",
    "user_message_bg",
    "assistant_message_bg",
    "thinking_bg",
    "tool_pending_bg",
    "tool_success_bg",
    "tool_error_bg",
    "action_needed_bg",
    "evidence_bg",
    "composer_bg",
)

PALETTES: dict[str, dict[str, str]] = {
    "studio_dark": {
        "accent": "#D68A4C",
        "border": "#4B5A5F",
        "border_accent": "#D68A4C",
        "border_muted": "#344044",
        "text": "#E8ECEA",
        "muted": "#A8B3AE",
        "dim": "#899690",
        "background": "#0F1214",
        "surface": "#151A1D",
        "surface_raised": "#1B2225",
        "focus_ring": "#F2A763",
        "success": "#69B58A",
        "warning": "#E3AC5B",
        "error": "#E06C75",
        "info": "#63A7D8",
        "pending": "#C9A0D7",
        "blocked": "#E28B77",
        "action_needed": "#F1B865",
        "selected_bg": "#263136",
        "user_message_bg": "#252C2B",
        "assistant_message_bg": "#181E21",
        "thinking_bg": "#1A2023",
        "tool_pending_bg": "#19242B",
        "tool_success_bg": "#17241D",
        "tool_error_bg": "#2A1B1E",
        "action_needed_bg": "#2B2317",
        "evidence_bg": "#182426",
        "composer_bg": "#111618",
    },
    "paper_light": {
        "accent": "#8E4E22",
        "border": "#9E9488",
        "border_accent": "#8E4E22",
        "border_muted": "#B8AFA3",
        "text": "#202725",
        "muted": "#56645E",
        "dim": "#65716C",
        "background": "#F7F4EF",
        "surface": "#FFFFFF",
        "surface_raised": "#EEE9E1",
        "focus_ring": "#7B3F18",
        "success": "#286D49",
        "warning": "#875715",
        "error": "#A93B43",
        "info": "#245F8B",
        "pending": "#6E437C",
        "blocked": "#933B2E",
        "action_needed": "#784B0F",
        "selected_bg": "#E4DDD3",
        "user_message_bg": "#E9E4DC",
        "assistant_message_bg": "#FFFFFF",
        "thinking_bg": "#F1EEE9",
        "tool_pending_bg": "#E7EFF3",
        "tool_success_bg": "#E5F0E9",
        "tool_error_bg": "#F5E5E6",
        "action_needed_bg": "#F4E9D4",
        "evidence_bg": "#E4EEEE",
        "composer_bg": "#FFFFFF",
    },
    "high_contrast": {
        "accent": "#FFD166",
        "border": "#FFFFFF",
        "border_accent": "#FFD166",
        "border_muted": "#C7C7C7",
        "text": "#FFFFFF",
        "muted": "#D7D7D7",
        "dim": "#BEBEBE",
        "background": "#000000",
        "surface": "#090909",
        "surface_raised": "#151515",
        "focus_ring": "#00E5FF",
        "success": "#7CFFB2",
        "warning": "#FFD166",
        "error": "#FF8A98",
        "info": "#7CCBFF",
        "pending": "#E2B8FF",
        "blocked": "#FFAA8F",
        "action_needed": "#FFE08A",
        "selected_bg": "#303030",
        "user_message_bg": "#202000",
        "assistant_message_bg": "#0C1820",
        "thinking_bg": "#181818",
        "tool_pending_bg": "#101D26",
        "tool_success_bg": "#102218",
        "tool_error_bg": "#291014",
        "action_needed_bg": "#29200D",
        "evidence_bg": "#102326",
        "composer_bg": "#080808",
    },
}

DEFAULT_PALETTE = "studio_dark"


def _hex(value: str) -> tuple[int, int, int]:
    if len(value) != 7 or not value.startswith("#"):
        raise ValueError(f"invalid theme color {value!r}")
    return (
        int(value[1:3], 16),
        int(value[3:5], 16),
        int(value[5:7], 16),
    )


def _linear(channel: int) -> float:
    value = channel / 255
    if value <= 0.04045:
        return value / 12.92
    return math.pow((value + 0.055) / 1.055, 2.4)


def contrast_ratio(foreground: str, background: str) -> float:
    first = sum(
        weight * _linear(channel)
        for weight, channel in zip(
            (0.2126, 0.7152, 0.0722),
            _hex(foreground),
            strict=True,
        )
    )
    second = sum(
        weight * _linear(channel)
        for weight, channel in zip(
            (0.2126, 0.7152, 0.0722),
            _hex(background),
            strict=True,
        )
    )
    light, dark = max(first, second), min(first, second)
    return (light + 0.05) / (dark + 0.05)


def contract() -> dict[str, object]:
    return {
        "default": DEFAULT_PALETTE,
        "roles": list(ROLES),
        "palettes": PALETTES,
    }
