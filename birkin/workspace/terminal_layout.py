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
    *,
    header: str,
    border: str,
    conversation: list[str],
    tabs: str,
    panel: list[str],
    composer: str,
    hints: str,
    rows: int,
) -> list[str]:
    trailing_chrome = [border, tabs, *panel, composer, hints]
    chrome = [header, border, *trailing_chrome]
    row_budget = max(0, rows)
    if row_budget < len(chrome):
        return chrome[-row_budget:] if row_budget else []

    conversation_budget = row_budget - len(chrome)
    visible_conversation = (
        conversation[-conversation_budget:] if conversation_budget else []
    )
    return [header, border, *visible_conversation, *trailing_chrome]
