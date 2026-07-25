"""Live provider calls through the engine — skipped unless the CLI is present.

The mocked tests prove the control flow; these prove the wiring. They are the
only place a real `codex` or `claude` process starts, they are marked `live`
so the offline suite stays offline, and they are deliberately tiny: the point
is that a real answer comes back through the real path, not that the model is
smart.
"""

from __future__ import annotations

import shutil

import pytest

from birkin import moirai
from birkin.moirai import journal

pytestmark = pytest.mark.live

HAS_CODEX = shutil.which("codex") is not None
HAS_CLAUDE = shutil.which("claude") is not None


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    yield tmp_path


def _script(tmp_path, body: str):
    p = tmp_path / "live.py"
    p.write_text(body, encoding="utf-8")
    return moirai.load_script(p)


@pytest.mark.skipif(not HAS_CODEX, reason="codex CLI not installed")
def test_codex_answers_in_free_text_through_the_engine(tmp_path):
    """No schema was asked for, so no schema comes back.

    This is the regression for the bug dogfooding found: the provider layer
    used to force CurationPlan's shape, and a one-word question came back as
    {"plan_version": 1, "summary": "서울", ...}.
    """
    script = _script(tmp_path, '''
meta = {"name": "live-codex", "roles": {"w": {"default": "codex:gpt-5.6-sol"}}}

def main(m):
    return m.agent("한 단어로만 답하세요: 대한민국의 수도는?", role="w")
''')
    out = moirai.run_script(script, cfg={})
    assert out["status"] == "completed" and out["agents"] == 1
    answer = (out["result"] or "").strip()
    assert "서울" in answer
    assert "plan_version" not in answer, "an application schema leaked back in"


@pytest.mark.skipif(not HAS_CLAUDE, reason="claude CLI not installed")
def test_claude_answers_through_the_engine(tmp_path):
    script = _script(tmp_path, '''
meta = {"name": "live-claude", "roles": {"w": {"default": "claude:haiku"}}}

def main(m):
    return m.agent("Answer with one word only: capital of France?", role="w")
''')
    out = moirai.run_script(script, cfg={})
    assert out["status"] == "completed"
    assert "paris" in (out["result"] or "").lower()


@pytest.mark.skipif(not (HAS_CODEX and HAS_CLAUDE),
                    reason="needs both CLIs")
def test_two_providers_run_in_one_workflow_and_in_parallel(tmp_path):
    """The engine's reason to exist: one run, two model families, concurrent.

    Asserting wall-clock beats the serial sum is what distinguishes real
    concurrency from a loop that merely finishes.
    """
    script = _script(tmp_path, '''
meta = {"name": "live-cross",
        "roles": {"a": {"default": "codex:gpt-5.6-sol"},
                  "b": {"default": "claude:haiku"}}}

def main(m):
    return m.parallel([
        lambda: m.agent("Reply with exactly: ALPHA", role="a"),
        lambda: m.agent("Reply with exactly: BETA", role="b"),
    ])
''')
    out = moirai.run_script(script, cfg={})
    assert out["status"] == "completed" and out["agents"] == 2
    first, second = out["result"]
    assert "ALPHA" in (first or "") and "BETA" in (second or "")

    calls = journal.run_calls(out["run_id"])
    assert {c["provider"] for c in calls} == {"codex", "claude"}

    from datetime import datetime
    spans = [(datetime.fromisoformat(c["started"]),
              datetime.fromisoformat(c["finished"])) for c in calls]
    wall = (max(e for _s, e in spans) - min(s for s, _e in spans)).total_seconds()
    serial = sum((e - s).total_seconds() for s, e in spans)
    assert wall < serial, f"ran sequentially: wall {wall}s vs serial {serial}s"


@pytest.mark.skipif(not HAS_CODEX, reason="codex CLI not installed")
def test_a_live_run_teaches_the_journal_what_it_costs(tmp_path):
    """The picker's estimates come from here — no observation, no estimate."""
    assert journal.observed("codex", "gpt-5.6-sol") is None
    script = _script(tmp_path, '''
meta = {"name": "live-observe", "roles": {"w": {"default": "codex:gpt-5.6-sol"}}}

def main(m):
    return m.agent("Reply with exactly: OK", role="w")
''')
    moirai.run_script(script, cfg={})
    seen = journal.observed("codex", "gpt-5.6-sol")
    assert seen and seen["n"] == 1 and seen["seconds"] > 0
