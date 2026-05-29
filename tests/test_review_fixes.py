"""Regression tests for the security/bug review follow-ups."""

from __future__ import annotations

import pytest

from birkin import llm
from birkin.gateway.core import match_command


def test_restart_with_hard_in_prose_is_soft_restart():
    # "hard" appearing as a word in the arg must NOT trigger a hard restart.
    assert match_command("/restart")[0] == "restart"
    assert match_command("/restart I worked hard today")[0] == "restart"
    assert match_command("/restart-gateway")[0] == "restart"
    # explicit flag still maps to hard restart
    assert match_command("/restart hard")[0] == "hard_restart"
    assert match_command("/restart --hard")[0] == "hard_restart"
    assert match_command("/hard_restart")[0] == "hard_restart"


def test_openai_empty_choices_raises_llmerror(monkeypatch):
    client = llm.LLMClient(provider="openai", model="gpt-4o",
                           api_key="k", base_url="https://example.invalid")

    class _Resp:
        def read(self):
            return b'{"choices": []}'  # content-filter / billing block shape

    monkeypatch.setattr(client, "_post", lambda *a, **k: _Resp())
    with pytest.raises(llm.LLMError):
        client._openai_complete("sys", [], None, "gpt-4o", None)
