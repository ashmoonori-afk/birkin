"""Birkin's outbound User-Agent must identify Birkin, not the project it learned from.

``tools/web.py`` shipped ``birkin/0.1 (+https://github.com/NousResearch/hermes-agent)``,
so every Marginalia / mwmbl / web_fetch request told the operator it came from
hermes-agent. Attribution to the inspiration belongs in ``pyproject.toml``'s
description (where it already is), never in a request header claiming to be
somebody else's crawler. The version also drifted: the package is well past 0.1.
"""

from __future__ import annotations

import birkin
from birkin.skills import hub
from birkin.tools import web


def test_user_agent_does_not_impersonate_another_project() -> None:
    assert "hermes-agent" not in web.USER_AGENT
    assert "NousResearch" not in web.USER_AGENT


def test_user_agent_names_birkin_and_its_real_version() -> None:
    assert web.USER_AGENT.startswith(f"birkin/{birkin.__version__}")


def test_user_agent_is_a_single_header_safe_line() -> None:
    assert "\n" not in web.USER_AGENT and "\r" not in web.USER_AGENT


def test_the_skills_hub_user_agent_still_names_birkin() -> None:
    """Regression guard on the surface that was already correct.

    skills/hub.py always sent its own name, which is what proved the web.py
    value was an omission rather than a deliberate policy. If that one drifts
    too, the reasoning behind this fix quietly stops holding.
    """
    assert "birkin" in hub.USER_AGENT.lower()
    assert "hermes-agent" not in hub.USER_AGENT
