"""Pure chat-primary terminal renderer for the shared workspace snapshot."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from .. import ui
from .terminal_layout import compose_layout, wrap_cells
from .theme import DEFAULT_PALETTE, sgr, sgr_background
from .theme import ansi256 as ansi256_palette

_STATE_MARKERS = {
    "not_started": ("·", "start", "muted"),
    "running": ("▸", "running", "info"),
    "pending": ("◇", "pending", "muted"),
    "paused": ("∥", "paused", "warning"),
    "succeeded": ("✓", "done", "success"),
    "failed": ("✗", "failed", "error"),
    "blocked": ("⊘", "blocked", "error"),
    "action_needed": ("◆", "action", "warning"),
    "unknown": ("?", "unknown", "muted"),
}


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        return {}
    return cast(dict[str, object], value)


def _sequence(value: object) -> Sequence[object]:
    if not isinstance(value, (list, tuple)):
        return ()
    return cast(Sequence[object], value)


def _line(text: str, width: int) -> str:
    return ui.pad(ui.fit(text.replace("\n", " "), width), width)


def _paint(
    role: str,
    text: str,
    *,
    color: bool,
    ansi_256: bool,
    palette: str,
) -> str:
    if not color:
        return text
    prefix = (
        f"\x1b[38;5;{ansi256_palette(palette)[role]}m"
        if ansi_256
        else sgr(role, palette)
    )
    background = sgr_background(
        "background",
        palette,
        ansi_256=ansi_256,
    )
    return f"{background}{prefix}{text}\x1b[0m"


def _conversation_lines(snapshot: Mapping[str, object], width: int) -> list[str]:
    entries = _sequence(snapshot.get("conversation"))
    if not entries:
        return [_line("No messages yet. Type below to start.", width)]
    lines: list[str] = []
    for raw in entries[-8:]:
        entry = _mapping(raw)
        text = entry.get("text")
        if not isinstance(text, str):
            continue
        kind = entry.get("kind")
        marker = "you" if kind == "user_message" else "birkin"
        lines.extend(wrap_cells(f"{marker} > {text}", width))
    return lines or [_line("No displayable messages.", width)]


def _panel_line(
    snapshot: Mapping[str, object],
    view: Mapping[str, object],
    width: int,
) -> str:
    panels = _sequence(snapshot.get("panels"))
    active = view.get("active_panel")
    parts: list[str] = []
    for raw in panels:
        panel = _mapping(raw)
        key = panel.get("key")
        if not isinstance(key, str):
            continue
        label = panel.get("label")
        name = label if isinstance(label, str) else key
        parts.append(f"[{name}]" if key == active else name)
    return _line("  ".join(parts), width)


def _active_panel_lines(
    snapshot: Mapping[str, object],
    view: Mapping[str, object],
    width: int,
    *,
    color: bool,
    ansi_256: bool,
    palette: str,
) -> list[str]:
    active = view.get("active_panel")
    selected = view.get("selected_item_id")
    for raw in _sequence(snapshot.get("panels")):
        panel = _mapping(raw)
        if panel.get("key") != active:
            continue
        label = panel.get("label")
        heading = (
            label if isinstance(label, str) else str(active).replace("_", " ").title()
        )
        lines = [
            _paint(
                "accent",
                _line(f"Panel · {heading}", width),
                color=color,
                ansi_256=ansi_256,
                palette=palette,
            )
        ]
        items = _sequence(panel.get("items"))
        if not items:
            lines.append(
                _paint(
                    "muted",
                    _line("  No items.", width),
                    color=color,
                    ansi_256=ansi_256,
                    palette=palette,
                )
            )
            return lines
        for raw_item in items[:4]:
            item = _mapping(raw_item)
            state = str(item.get("ui_state") or "unknown")
            marker, state_label, role = _STATE_MARKERS.get(
                state,
                _STATE_MARKERS["unknown"],
            )
            summary = str(
                item.get("summary")
                or item.get("title")
                or item.get("name")
                or item.get("id")
                or "item"
            )
            prefix = ">" if item.get("id") == selected else " "
            lines.append(
                _paint(
                    role,
                    _line(
                        f"{prefix} {marker} {state_label} · {summary}",
                        width,
                    ),
                    color=color,
                    ansi_256=ansi_256,
                    palette=palette,
                )
            )
        return lines
    return [
        _paint(
            "error",
            _line("Panel unavailable.", width),
            color=color,
            ansi_256=ansi_256,
            palette=palette,
        )
    ]


def _composer_line(snapshot: Mapping[str, object], width: int) -> str:
    composer = _mapping(snapshot.get("composer"))
    draft = composer.get("draft")
    value = draft if isinstance(draft, str) else ""
    return _line(f"message > {value}", width)


def render_terminal(
    snapshot: Mapping[str, object],
    view: Mapping[str, object],
    size: tuple[int, int],
    *,
    color: bool = False,
    ansi_256: bool = False,
    palette: str = DEFAULT_PALETTE,
) -> tuple[str, ...]:
    """Render one width-safe terminal workspace frame.

    Color is intentionally a presentation adapter concern; the base frame stays
    readable when ``color`` is false and later semantic theme mappings may wrap
    individual roles without changing layout.
    """

    columns, rows = size
    width = max(20, columns)

    def painted(role: str, text: str) -> str:
        return _paint(
            role,
            _line(text, width),
            color=color,
            ansi_256=ansi_256,
            palette=palette,
        )

    status = _mapping(snapshot.get("status"))
    connection = str(status.get("connection") or "unknown")
    frame = compose_layout(
        width,
        header=painted("accent", "Birkin Workspace · Conversation"),
        border=painted("border_muted", "─" * width),
        conversation=[
            painted("text", line) for line in _conversation_lines(snapshot, width)
        ],
        tabs=painted("muted", _panel_line(snapshot, view, width)),
        panel=_active_panel_lines(
            snapshot,
            view,
            width,
            color=color,
            ansi_256=ansi_256,
            palette=palette,
        ),
        composer=painted("text", _composer_line(snapshot, width)),
        pulse=painted("info", f"Pulse · {connection}"),
        hints=painted(
            "dim",
            "keys · Tab panels · ↑/↓ items · Enter open · Esc back",
        ),
        wide_label=painted(
            "muted",
            "Ledger (34) │ Bench · Conversation │ Pulse · " + connection,
        ),
        bench_label=painted("muted", "Bench · Conversation"),
        queue_label=painted("warning", "Attention Queue"),
    )
    return tuple(frame[-max(1, rows) :])
