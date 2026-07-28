"""The cached system prefix must stay byte-stable across turns.

cache_control marks the system block and the tool list as ephemeral-cacheable,
but that only pays off if the bytes repeat. Slip anything per-turn into the
prefix — a clock, a request-scoped snippet, an unsorted skill list — and every
turn silently pays full input price. hermes spent a release window on exactly
this ("byte-stable gateway system prompts"); these tests are what stops the
same regression here.
"""

from __future__ import annotations

import pytest

from birkin import config, promptgate
from birkin.memory import Memory


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    yield tmp_path


def _system(mem: Memory, cfg: dict) -> str:
    return promptgate.compose_main(cfg, skills_index="SKILLS",
                                   memory_block=mem.render())


def test_system_prompt_is_identical_on_two_consecutive_turns():
    cfg = config.load_config()
    mem = Memory(cfg)
    mem.write_note("Preference", "한국어로 대화", note_type="preference",
                   source="test")
    assert _system(mem, cfg) == _system(mem, cfg)


def test_system_prompt_carries_no_wall_clock():
    """A timestamp in the prefix would invalidate the cache every turn."""
    import re
    cfg = config.load_config()
    text = _system(Memory(cfg), cfg)
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", text)
    assert not re.search(r"\b\d{2}:\d{2}:\d{2}\b", text)


def test_reading_memory_does_not_perturb_the_prefix():
    """Search potentiates note dynamics; that must not leak into the prompt."""
    cfg = config.load_config()
    mem = Memory(cfg)
    mem.write_note("Cluster ingress", "k8s ingress 설정", source="test")
    before = _system(mem, cfg)
    mem.search("ingress")
    assert _system(mem, cfg) == before


def test_cache_control_is_still_attached_to_the_cacheable_blocks():
    import inspect

    from birkin import llm
    src = inspect.getsource(llm)
    assert src.count('"cache_control": {"type": "ephemeral"}') >= 2
    assert 't[-1]["cache_control"]' in src        # the tool list too
