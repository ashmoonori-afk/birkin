"""Markdown -> Telegram HTML rendering + size-safe splitting + send fallback."""

from __future__ import annotations

import re

from birkin.gateway.channels import tg_format as tf

# Telegram-supported HTML tags (parse_mode="HTML"); anything else 400s.
_ALLOWED = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
            "code", "pre", "a", "blockquote", "span"}


def _tags(html: str) -> set[str]:
    return {re.sub(r"[\s/>].*$", "", t.lstrip("</").rstrip(">")).lower()
            for t in re.findall(r"</?[a-zA-Z][^>]*>", html)}


def test_only_supported_tags_emitted():
    html = tf.to_html("# H\n\n**b** _i_ ~~s~~ `c`\n\n> quote\n\n- item\n\n"
                      "[t](http://x)\n\n```\ncode\n```")
    assert _tags(html) <= _ALLOWED


def test_bold_italic_strike_code_heading():
    assert "<b>bold</b>" in tf.to_html("**bold**")
    assert "<b>bold</b>" in tf.to_html("__bold__")
    assert "<i>it</i>" in tf.to_html("*it*")
    assert "<s>x</s>" in tf.to_html("~~x~~")
    assert "<code>y</code>" in tf.to_html("`y`")
    assert "<b>Title</b>" in tf.to_html("## Title")


def test_escapes_html_special_chars():
    out = tf.to_html("a < b & c > d")
    assert "&lt;" in out and "&amp;" in out and "&gt;" in out
    assert "< b" not in out  # the raw '<' must not survive


def test_link_renders_anchor_and_escapes_ampersand_in_url():
    out = tf.to_html("[ClawHub](https://x.io?a=1&b=2)")
    assert '<a href="https://x.io?a=1&amp;b=2">ClawHub</a>' in out


def test_fenced_code_block_is_pre_and_escaped():
    out = tf.to_html("```python\nprint('a < b & c')\n```")
    assert "<pre>" in out and "</pre>" in out
    assert "&lt;" in out and "&amp;" in out
    assert "**" not in out  # nothing inside the fence is reinterpreted


def test_inline_markers_inside_code_are_not_formatted():
    out = tf.to_html("`a**b**c`")
    assert "<code>a**b**c</code>" in out  # literal, not <b>


def test_table_becomes_stacked_mobile_cards():
    md = "| A | B |\n|---|---|\n| 1 | longer |\n| 22 | x |"
    out = tf.to_html(md)
    assert "<pre>" not in out
    assert "<b>A: 1</b>" in out
    assert "• <b>B:</b> longer" in out
    assert "<b>A: 22</b>" in out
    assert "• <b>B:</b> x" in out
    assert "|" not in out and "---" not in out


def test_wide_stock_table_uses_labeled_mobile_rows():
    md = (
        "| 종목 | 기준가 | 1차 진입 | 손절·탈출 기준 | 6~12개월 목표 | 3년 목표 | 판단 |\n"
        "|---|---|---|---|---|---|---|\n"
        "| SPY | 약 $741 | $700~725 | $665 이탈 | $800~835 | $950~1,050 | 최우선 핵심자산 |\n"
        "| 삼성전자 | 약 254,000원 | 225,000~245,000원 | 200,000원 이탈 | "
        "300,000~340,000원 | 400,000~500,000원 | 한국 대형주 중 선호 |"
    )
    out = tf.to_html(md)
    assert "<pre>" not in out
    assert "<b>종목: SPY</b>" in out
    assert "• <b>1차 진입:</b> $700~725" in out
    assert "• <b>3년 목표:</b> $950~1,050" in out
    assert "<b>종목: 삼성전자</b>" in out
    assert "• <b>판단:</b> 한국 대형주 중 선호" in out


def test_blockquote():
    out = tf.to_html("> hello\n> world")
    assert out.startswith("<blockquote>") and "</blockquote>" in out
    assert "hello" in out and "world" in out


def test_no_placeholder_leak():
    out = tf.to_html("`code` and ```\nblock\n``` and | a | b |\n|---|---|\n| 1 | 2 |")
    assert "\x00" not in out


def test_bullets_become_dots():
    out = tf.to_html("- one\n- two")
    assert "• one" in out and "• two" in out


def test_triple_emphasis_is_bold_italic():
    assert tf.to_html("***x***") == "<b><i>x</i></b>"
    assert tf.to_html("___y___") == "<b><i>y</i></b>"


def test_crossed_emphasis_degrades_without_breaking_tags():
    # Overlapping (not nested) delimiters would emit crossed tags Telegram 400s;
    # the balancer strips emphasis instead, keeping the text and valid HTML.
    for md in ("**a _b** c_", "**a ~~b** c~~", "~~s _i~~ x_"):
        out = tf.to_html(md)
        assert _balanced(out), out
        assert _tags(out) <= _ALLOWED


def test_href_with_quote_is_escaped():
    out = tf.to_html('[k](http://x/?a="b")')
    assert '<a href="http://x/?a=&quot;b&quot;">k</a>' in out
    assert '"b"' not in out.replace("&quot;", "")  # raw quote can't break attr


def _balanced(html: str) -> bool:
    stack = []
    for m in re.finditer(r"</?[a-zA-Z]+", html):
        t = m.group()
        if t[1] == "/":
            if not stack or stack.pop() != t[2:]:
                return False
        else:
            stack.append(t[1:])
    return not stack


# ---------------- splitting ----------------------------------------------

def test_split_keeps_chunks_under_limit():
    big = "\n".join(f"line {i} " + "x" * 50 for i in range(400))
    chunks = tf.split(tf.to_html(big), limit=1000)
    assert len(chunks) > 1
    assert all(tf._tg_len(c) <= 1000 for c in chunks)


def test_split_never_breaks_a_pre_block():
    inner = "\n".join(f"row{i} " + "y" * 40 for i in range(200))
    html = f"<pre>{inner}</pre>"
    for c in tf.split(html, limit=800):
        # every chunk has balanced <pre> tags (open count == close count)
        assert c.count("<pre>") == c.count("</pre>")
        assert tf._tg_len(c) <= 800


def test_short_message_is_single_chunk():
    assert tf.split(tf.to_html("hi there")) == ["hi there"]


def test_to_plain_strips_tags_and_unescapes():
    html = tf.to_html("**b** and `a < b`")
    plain = tf.to_plain(html)
    assert "<b>" not in plain and "<code>" not in plain and "</" not in plain
    assert "&lt;" not in plain and "&amp;" not in plain  # entities decoded
    assert "a < b" in plain and "**" not in plain        # literal content kept


# ---------------- send integration ---------------------------------------

def _channel(monkeypatch, results):
    from birkin.gateway.channels.telegram import TelegramChannel
    ch = TelegramChannel(token="x")
    sent = []

    def fake_call(method, params, timeout=60):
        sent.append({"method": method, **params})
        return results.pop(0) if results else {"ok": True}

    monkeypatch.setattr(ch, "_call", fake_call)
    return ch, sent


def test_send_reply_uses_html_parse_mode(monkeypatch):
    ch, sent = _channel(monkeypatch, [{"ok": True}])
    ch._send_reply("c1", "**hello** world")
    assert len(sent) == 1
    assert sent[0]["parse_mode"] == "HTML"
    assert "<b>hello</b>" in sent[0]["text"]


def test_send_reply_falls_back_to_plain_when_html_rejected(monkeypatch):
    # First call (HTML) returns not-ok -> the chunk is resent as plain text.
    ch, sent = _channel(monkeypatch, [{"ok": False, "description": "bad entity"},
                                      {"ok": True}])
    ch._send_reply("c1", "**hello**")
    assert len(sent) == 2
    assert sent[0]["parse_mode"] == "HTML"
    assert "parse_mode" not in sent[1]          # plain fallback
    assert "<b>" not in sent[1]["text"]          # tags stripped
    assert "hello" in sent[1]["text"]
