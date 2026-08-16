"""Width-specific terminal workspace composition."""

from __future__ import annotations

from .. import ui


def wrap_cells(text: str, width: int) -> list[str]:
    words = text.replace("\n", " ").split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if ui.cell_width(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        remainder = word
        while ui.cell_width(remainder) > width:
            piece = ui.fit(remainder, width, marker="")
            lines.append(piece)
            remainder = remainder[len(piece):]
        current = remainder
    if current or not lines:
        lines.append(current)
    return lines


def compose_layout(
    width: int,
    *,
    header: str,
    border: str,
    conversation: list[str],
    tabs: str,
    panel: list[str],
    composer: str,
    pulse: str,
    hints: str,
    wide_label: str,
    bench_label: str,
    queue_label: str,
) -> list[str]:
    if width >= 120:
        return [
            header,
            wide_label,
            border,
            *conversation,
            border,
            tabs,
            *panel,
            composer,
            hints,
        ]
    if width >= 80:
        return [
            pulse,
            header,
            bench_label,
            *conversation,
            border,
            tabs,
            *panel,
            composer,
            hints,
        ]
    return [
        pulse,
        queue_label,
        tabs,
        *panel,
        border,
        bench_label,
        *conversation,
        composer,
        hints,
    ]
