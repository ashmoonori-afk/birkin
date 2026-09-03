r"""A URL that arrives markdown-escaped must reach the agent unescaped.

A Telegram client that formats an outgoing link escapes the characters
markdown treats specially, so a tracking URL arrives as

    ...?utm_medium=email&utm\_source=...

birkin passed msg["text"] through verbatim, so the agent received a URL whose
query string contains a literal backslash. Fetching it asks for a parameter
named ``utm\_source``, which is not the parameter anyone meant -- and the
model, seeing a page that does not answer, retries until the turn's budget is
gone. That is the front half of a 900-second timeout.

Telegram already tells us the truth: a ``text_link`` entity carries the real
URL, and ``url`` entities carry byte offsets into the text. Where an entity
exists it is authoritative. Where none does, only the escape sequences
markdown actually defines are undone -- a lone backslash, or one before a
character that is not a markdown special, is left exactly as it is, because
birkin is routinely handed Windows paths and regexes in chat.
"""

from __future__ import annotations

from birkin.gateway.channels import telegram as tg

KAGGLE = ("https://www.kaggle.com/competitions/kaggriculture"
          "?utm_medium=email&utm_source=newsletter")


class TestEscapedUrlIsRecovered:
    def test_the_reported_url_loses_its_backslash(self) -> None:
        text = ("https://www.kaggle.com/competitions/kaggriculture"
                r"?utm_medium=email&utm\_source=newsletter")
        assert tg.recover_inbound_text(text, []) == KAGGLE

    def test_several_escapes_in_one_url(self) -> None:
        text = r"https://x.test/a\_b\_c?d\_e=1"
        assert tg.recover_inbound_text(text, []) == "https://x.test/a_b_c?d_e=1"

    def test_escaped_markdown_specials_in_prose_are_unescaped(self) -> None:
        assert tg.recover_inbound_text(r"a \* b \_ c", []) == "a * b _ c"


class TestThingsThatMustNotBeTouched:
    def test_a_windows_path_survives(self) -> None:
        """The single most likely thing a user pastes into this bot."""
        text = r"C:\Users\lg\Documents\Birkin"
        assert tg.recover_inbound_text(text, []) == text

    def test_a_regex_escape_survives(self) -> None:
        text = r"grep -E '\d+\s+\w' file.txt"
        assert tg.recover_inbound_text(text, []) == text

    def test_a_trailing_backslash_survives(self) -> None:
        assert tg.recover_inbound_text("end of line \\", []) == "end of line \\"

    def test_a_doubled_backslash_is_one_literal_backslash(self) -> None:
        assert tg.recover_inbound_text(r"a \\ b", []) == r"a \ b"

    def test_plain_text_is_returned_unchanged(self) -> None:
        text = "just a normal message about underscores_and_things"
        assert tg.recover_inbound_text(text, []) is text


class TestEntitiesAreAuthoritative:
    def test_a_text_link_entity_supplies_the_real_url(self) -> None:
        """A hyperlinked word carries a URL that is nowhere in the text."""
        entities = [{"type": "text_link", "offset": 0, "length": 9,
                     "url": KAGGLE}]
        out = tg.recover_inbound_text("this comp", entities)
        assert KAGGLE in out

    def test_a_text_link_is_not_appended_twice(self) -> None:
        entities = [{"type": "text_link", "offset": 0, "length": 5,
                     "url": KAGGLE}]
        assert tg.recover_inbound_text(f"click {KAGGLE}", entities).count(KAGGLE) == 1

    def test_a_malformed_entity_cannot_break_the_message(self) -> None:
        assert tg.recover_inbound_text("hello", [{"type": "text_link"}]) == "hello"
        assert tg.recover_inbound_text("hello", ["not-a-dict"]) == "hello"

    def test_no_entities_is_the_ordinary_case(self) -> None:
        assert tg.recover_inbound_text("hello", None) == "hello"
