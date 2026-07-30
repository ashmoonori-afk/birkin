"""Render the agent's GitHub-flavored Markdown into Telegram-safe HTML.

The gateway agent emits rich GFM (``**bold**``, ``# headings``, ``|`` tables,
fenced code, lists, links). Telegram's ``sendMessage`` shows plain text *as-is*,
so that markup arrives raw and broken (literal ``**``, ``|---|``, ``##``). This
module converts that GFM into the small HTML subset Telegram *does* render via
``parse_mode="HTML"``: ``b · i · u · s · code · pre · a · blockquote``.

Why HTML and not MarkdownV2: HTML mode only needs ``& < >`` escaped, whereas
MarkdownV2 must escape ~18 characters *everywhere* and returns 400 on a single
stray ``.``/``-``/``!`` — fragile for arbitrary model output. Telegram supports
no table or heading tags, so tables become stacked labeled cards that fit a
phone viewport and headings become bold lines.

Pure standard library. The caller (telegram channel) falls back to plain text if
Telegram ever rejects the HTML, so a converter edge case can never drop a reply.
"""

from __future__ import annotations

import re

TG_LIMIT = 4096          # Telegram hard cap per message, in UTF-16 code units
_SAFE_LIMIT = 3900       # leave headroom (emojis cost 2 units; tag overhead)

_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
_BOLDITALIC_RE = re.compile(r"\*\*\*(.+?)\*\*\*|___(.+?)___")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC_RE = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])"
                        r"|(?<![\w_])_(?!\s)([^_\n]+?)(?<!\s)_(?![\w_])")
_STRIKE_RE = re.compile(r"~~(.+?)~~")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_HR_RE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.+)$")
_SEP_CELL_RE = re.compile(r"^:?-{1,}:?$")
_PLACEHOLDER = "\x00{}\x00"
_PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")
_EMPH_TAG_RE = re.compile(r"</?[bis]>")  # the emphasis tags _inline emits


def _esc(s: str) -> str:
    """Escape the only three chars Telegram HTML treats specially in text."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _esc_attr(s: str) -> str:
    """Escape for a double-quoted HTML attribute (href) — also the quote, so a
    URL containing ``"`` can't terminate the attribute early (Telegram 400)."""
    return _esc(s).replace('"', "&quot;")


def _strip_inline_md(s: str) -> str:
    """Drop emphasis/code markers from a table cell (it renders as monospace)."""
    s = _BOLD_RE.sub(lambda m: m.group(1) or m.group(2), s)
    s = _STRIKE_RE.sub(lambda m: m.group(1), s)
    s = s.replace("`", "")
    # lone emphasis underscores/asterisks around words
    s = re.sub(r"(?<!\w)[*_](.+?)[*_](?!\w)", r"\1", s)
    return s.strip()


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _is_separator(line: str) -> bool:
    cells = _split_row(line)
    return bool(cells) and all(_SEP_CELL_RE.match(c) for c in cells if c != "" or len(cells) == 1) \
        and any(c for c in cells)


def _render_table_cards(header: list[str], rows: list[list[str]]) -> str:
    cols = max([len(header)] + [len(r) for r in rows] or [0])

    def cell(r: list[str], i: int) -> str:
        return _strip_inline_md(r[i]) if i < len(r) else ""

    labels = [cell(header, i) or f"열 {i + 1}" for i in range(cols)]
    cards: list[str] = []
    for row in rows:
        values = [cell(row, i) for i in range(cols)]
        if not any(values):
            continue
        title = f"{labels[0]}: {values[0]}" if values[0] else labels[0]
        lines = [f"<b>{_esc(title)}</b>"]
        lines.extend(
            f"• <b>{_esc(labels[i])}:</b> {_esc(values[i])}"
            for i in range(1, cols)
            if values[i]
        )
        cards.append("\n".join(lines))
    return "\n\n".join(cards)


def to_html(md: str) -> str:
    """Convert GFM ``md`` to Telegram-renderable HTML (parse_mode="HTML")."""
    md = (md or "").replace("\r\n", "\n").replace("\r", "\n")
    stash: list[str] = []

    def put(frag: str) -> str:
        stash.append(frag)
        return _PLACEHOLDER.format(len(stash) - 1)

    # 1. Fenced code blocks first, so nothing inside them is reinterpreted.
    md = _FENCE_RE.sub(
        lambda m: "\n" + put(f"<pre>{_esc(m.group(1).rstrip(chr(10)))}</pre>") + "\n", md)

    # 2. Pipe tables -> stacked labeled cards (Telegram has no <table>).
    md = _tables_to_cards(md, put)

    # 3. Inline code, links — captured from raw text, escaped into stable tags.
    md = _INLINE_CODE_RE.sub(lambda m: put(f"<code>{_esc(m.group(1))}</code>"), md)
    md = _LINK_RE.sub(
        lambda m: put(f'<a href="{_esc_attr(m.group(2))}">{_esc(m.group(1))}</a>'), md)

    # 4. Escape everything else, then apply emphasis on the escaped text
    #    (the * _ ~ # > markers survive HTML escaping).
    out_lines: list[str] = []
    bq: list[str] = []

    def flush_bq() -> None:
        if bq:
            out_lines.append("<blockquote>" + "\n".join(bq) + "</blockquote>")
            bq.clear()

    for raw in md.split("\n"):
        line = _esc(raw)
        if _HR_RE.match(raw):
            flush_bq()
            out_lines.append("──────────")
            continue
        h = _HEADING_RE.match(raw)
        if h:
            flush_bq()
            out_lines.append("<b>" + _inline(_esc(h.group(1))) + "</b>")
            continue
        if raw.lstrip().startswith(">"):
            bq.append(_inline(_esc(raw.lstrip()[1:].lstrip())))
            continue
        flush_bq()
        b = _BULLET_RE.match(raw)
        if b:
            out_lines.append(f"{b.group(1)}• " + _inline(_esc(b.group(2))))
            continue
        out_lines.append(_inline(line))
    flush_bq()

    text = "\n".join(out_lines)
    # 5. Restore the protected code/table/link/blockquote-safe fragments.
    text = _PLACEHOLDER_RE.sub(lambda m: stash[int(m.group(1))], text)
    # Collapse the blank lines the fenced-code guard may have introduced.
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _inline(escaped: str) -> str:
    """Bold/italic/strikethrough on already-HTML-escaped text, with the output
    guaranteed tag-balanced (Telegram 400s on crossed/overlapping tags)."""
    escaped = _BOLDITALIC_RE.sub(            # ***x*** / ___x___  -> bold+italic
        lambda m: f"<b><i>{m.group(1) or m.group(2)}</i></b>", escaped)
    escaped = _BOLD_RE.sub(
        lambda m: f"<b>{m.group(1) or m.group(2)}</b>", escaped)
    escaped = _STRIKE_RE.sub(lambda m: f"<s>{m.group(1)}</s>", escaped)
    escaped = _ITALIC_RE.sub(
        lambda m: f"<i>{m.group(1) or m.group(2) or m.group(3) or m.group(4)}</i>",
        escaped)
    return _balance_emphasis(escaped)


def _balance_emphasis(s: str) -> str:
    """Return ``s`` unchanged if its b/i/s tags nest properly; otherwise strip
    ALL of them, keeping the text. The three independent emphasis passes can
    interleave tags for pathological input (e.g. ``**a _b** c_`` -> crossed),
    which Telegram rejects; stripping degrades gracefully without a 400."""
    stack: list[str] = []
    for m in _EMPH_TAG_RE.finditer(s):
        tag = m.group()
        if tag[1] == "/":
            if not stack or stack[-1] != tag[2]:
                return _EMPH_TAG_RE.sub("", s)
            stack.pop()
        else:
            stack.append(tag[1])
    return _EMPH_TAG_RE.sub("", s) if stack else s


def _tables_to_cards(md: str, put) -> str:
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        if ("|" in lines[i] and i + 1 < n and "|" in lines[i + 1]
                and _is_separator(lines[i + 1])):
            header = _split_row(lines[i])
            j = i + 2
            rows: list[list[str]] = []
            while j < n and lines[j].strip() and "|" in lines[j]:
                rows.append(_split_row(lines[j]))
                j += 1
            out.append(put(_render_table_cards(header, rows)))
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def _tg_len(s: str) -> int:
    """Telegram counts length in UTF-16 code units (astral chars cost 2)."""
    return len(s.encode("utf-16-le")) // 2


def split(html: str, limit: int = _SAFE_LIMIT) -> list[str]:
    """Split rendered HTML into Telegram-sized chunks on safe boundaries.

    Never splits inside a ``<pre>`` block (that would break the tag); an oversized
    ``<pre>`` is broken into multiple ``<pre>`` blocks along its inner lines.
    """
    blocks = re.split(r"(<pre>.*?</pre>|<blockquote>.*?</blockquote>)",
                      html, flags=re.DOTALL)
    chunks: list[str] = []
    cur = ""

    def push() -> None:
        nonlocal cur
        if cur.strip():
            chunks.append(cur.strip("\n"))
        cur = ""

    def add(piece: str) -> None:
        nonlocal cur
        if _tg_len(cur) + _tg_len(piece) <= limit:
            cur += piece
        else:
            push()
            cur = piece

    for block in blocks:
        if not block:
            continue
        if block.startswith("<pre>") and _tg_len(block) > limit:
            push()
            chunks.extend(_split_wrapped(block, "pre", limit))
            continue
        if block.startswith("<blockquote>") and _tg_len(block) > limit:
            push()
            chunks.extend(_split_wrapped(block, "blockquote", limit))
            continue
        if _tg_len(block) <= limit:
            add(block)
            continue
        # A long non-pre run: split on line boundaries.
        for ln in block.split("\n"):
            seg = ln + "\n"
            if _tg_len(seg) > limit:                 # pathological single line
                for hard in _hard_split(seg, limit):
                    add(hard)
            else:
                add(seg)
    push()
    return chunks or [""]


def _split_wrapped(block: str, tag: str, limit: int) -> list[str]:
    """Split an oversized ``<tag>…</tag>`` block along its inner lines into
    several VALID ``<tag>…</tag>`` blocks, so a tag is never torn across chunks."""
    open_t, close_t = f"<{tag}>", f"</{tag}>"
    inner = block[len(open_t):-len(close_t)]
    overhead = len(open_t) + len(close_t)
    parts: list[str] = []
    cur: list[str] = []
    size = 0
    for ln in inner.split("\n"):
        add = _tg_len(ln) + 1
        if size + add > limit - overhead and cur:
            parts.append(open_t + "\n".join(cur) + close_t)
            cur, size = [], 0
        cur.append(ln)
        size += add
    if cur:
        parts.append(open_t + "\n".join(cur) + close_t)
    return parts


def _hard_split(s: str, limit: int) -> list[str]:
    return [s[i:i + limit] for i in range(0, len(s), limit)]


_TAG_RE = re.compile(r"<[^>]+>")


def to_plain(html: str) -> str:
    """Strip HTML back to readable plain text — the no-parse_mode fallback."""
    s = _TAG_RE.sub("", html)
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
            .strip())
