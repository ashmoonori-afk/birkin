"""Strip think blocks from visible text; repair broken message sequences.

Some open models leak ``<think>`` into assistant content, and a few endpoints
drop the closing tag entirely. Histories replayed after crashes can carry
consecutive same-role messages or assistant turns that are thinking-only.
"""

from __future__ import annotations

from birkin.reasoning import repair_messages, strip_think_blocks


class TestStripThinkBlocks:
    def test_closed_pair_is_removed(self) -> None:
        assert strip_think_blocks("<think>secret</think>Hello") == "Hello"

    def test_variant_tags_case_insensitive(self) -> None:
        assert strip_think_blocks("<THINKING>x</THINKING>ok") == "ok"
        assert strip_think_blocks("<reasoning>x</reasoning>ok") == "ok"
        assert strip_think_blocks("<thought>x</thought>ok") == "ok"

    def test_unterminated_open_tag_at_block_start_strips_to_end(self) -> None:
        assert strip_think_blocks("<think>never closed, model died") == ""
        out = strip_think_blocks("visible\n<think>tail lost")
        assert out == "visible"

    def test_prose_mention_mid_sentence_is_preserved(self) -> None:
        text = "Use the <think> tag to hide reasoning."
        assert strip_think_blocks(text) == text

    def test_empty_input(self) -> None:
        assert strip_think_blocks("") == ""


class TestRepairMessages:
    def test_consecutive_same_role_messages_are_merged(self) -> None:
        msgs = [{"role": "user", "content": "a"},
                {"role": "user", "content": "b"},
                {"role": "assistant", "content": "ok"}]
        out = repair_messages(msgs)
        assert [m["role"] for m in out] == ["user", "assistant"]
        merged = out[0]["content"]
        assert "a" in str(merged) and "b" in str(merged)

    def test_thinking_only_assistant_message_is_dropped(self) -> None:
        msgs = [{"role": "user", "content": "q"},
                {"role": "assistant", "content": "<think>only thoughts</think>"},
                {"role": "user", "content": "again"}]
        out = repair_messages(msgs)
        assert [m["role"] for m in out] == ["user"]
        assert "only thoughts" not in str(out)

    def test_input_list_is_not_mutated(self) -> None:
        msgs = [{"role": "user", "content": "a"},
                {"role": "user", "content": "b"}]
        snapshot = [dict(m) for m in msgs]
        repair_messages(msgs)
        assert msgs == snapshot

    def test_healthy_sequence_is_returned_unchanged(self) -> None:
        msgs = [{"role": "user", "content": "q"},
                {"role": "assistant", "content": "a"}]
        assert repair_messages(msgs) == msgs
