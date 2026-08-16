"""P1-1a: opt-in warm CLI session for the REPL (reuse one process)."""

from __future__ import annotations


def _session(tmp_path, monkeypatch, **over):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    from birkin.runtime import build_session
    cfg = {**config.DEFAULT_CONFIG, "provider": "claude-cli",
           "model": "haiku", "checkpoints": False, **over}
    config.save_config(cfg)
    return build_session(cfg)


class _FakeWarm:
    def __init__(self):
        self.asks: list[str] = []
        self.closed = False

    def ask(self, text, on_text=None):
        self.asks.append(text)
        if on_text:
            on_text("warm reply")
        return "warm reply"

    def close(self):
        self.closed = True


def test_warm_off_by_default_uses_agent_run(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch)                 # flag not set
    assert s._use_warm() is False
    called = {"agent": 0}
    monkeypatch.setattr(s.agent, "run",
                        lambda *a, **k: called.__setitem__("agent", 1) or "x")
    s.ask("hi")
    assert called["agent"] == 1                         # legacy path
    assert s._warm is None                              # no warm process built


def test_warm_on_routes_to_warm_session_and_reuses_it(tmp_path, monkeypatch):
    s = _session(tmp_path, monkeypatch, repl_warm_session=True)
    assert s._use_warm() is True
    fake = _FakeWarm()
    monkeypatch.setattr(s, "_build_warm", lambda: fake)
    monkeypatch.setattr(s.agent, "run",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("agent.run must not run on warm path")))
    pieces: list[str] = []
    assert s.ask("first", on_text=pieces.append) == "warm reply"
    assert s.ask("second") == "warm reply"
    assert [text.rsplit("## User request\n\n", 1)[-1]
            for text in fake.asks] == ["first", "second"]  # SAME process reused
    assert pieces == ["warm reply"]                     # on_text threaded
    s.close()
    assert fake.closed is True and s._warm is None


def test_warm_turn_preloads_routed_skill_body_and_path(tmp_path, monkeypatch):
    skill_dir = tmp_path / "skills" / "blog-helper"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: blog-helper\ndescription: research a company blog\n---\n\n"
        "UNIQUE-WARM-SKILL-BODY\n",
        encoding="utf-8",
    )
    s = _session(tmp_path, monkeypatch, provider="codex-cli",
                 repl_warm_session=True, self_improve=False)
    fake = _FakeWarm()
    monkeypatch.setattr(s, "_build_warm", lambda: fake)
    s.ask("research the company blog")
    assert "UNIQUE-WARM-SKILL-BODY" in fake.asks[0]
    assert str(skill_dir) in fake.asks[0]


def test_warm_turn_does_not_repeat_skill_already_in_child_context(
        tmp_path, monkeypatch):
    skill_dir = tmp_path / "skills" / "blog-helper"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: blog-helper\ndescription: research a company blog\n---\n\n"
        "UNIQUE-WARM-SKILL-BODY\n",
        encoding="utf-8",
    )
    s = _session(tmp_path, monkeypatch, provider="codex-cli",
                 repl_warm_session=True, self_improve=False)
    fake = _FakeWarm()
    monkeypatch.setattr(s, "_build_warm", lambda: fake)

    s.ask("research the company blog")
    s.ask("research the company blog again")

    assert "UNIQUE-WARM-SKILL-BODY" in fake.asks[0]
    assert "UNIQUE-WARM-SKILL-BODY" not in fake.asks[1]


def test_warm_turn_reloads_edited_skill_into_child_context(tmp_path, monkeypatch):
    skill_dir = tmp_path / "skills" / "blog-helper"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "---\nname: blog-helper\ndescription: research a company blog\n---\n\n"
        "OLD-SKILL-BODY\n",
        encoding="utf-8",
    )
    s = _session(tmp_path, monkeypatch, provider="codex-cli",
                 repl_warm_session=True, self_improve=False)
    fake = _FakeWarm()
    monkeypatch.setattr(s, "_build_warm", lambda: fake)
    s.ask("research the company blog")
    skill_path.write_text(
        "---\nname: blog-helper\ndescription: research a company blog\n---\n\n"
        "NEW-SKILL-BODY\n",
        encoding="utf-8",
    )
    s.skills.reload()

    s.ask("research the company blog")

    assert "NEW-SKILL-BODY" in fake.asks[1]


def test_warm_disabled_for_non_cli_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    s = _session(tmp_path, monkeypatch, provider="anthropic",
                 repl_warm_session=True)
    assert s._use_warm() is False                       # API path never warms


def test_untrusted_turn_bypasses_warm_and_harness_review(
        tmp_path, monkeypatch):
    import pytest

    s = _session(
        tmp_path,
        monkeypatch,
        repl_warm_session=True,
        self_improve=False,
    )
    monkeypatch.setattr(
        s,
        "_warm_ask",
        lambda *_args, **_kwargs: pytest.fail(
            "untrusted turn reached the trusted warm child"
        ),
    )
    run_kwargs: dict[str, object] = {}
    record_kwargs: dict[str, object] = {}

    def run(_text: str, **kwargs: object) -> str:
        run_kwargs.update(kwargs)
        return "safe"

    monkeypatch.setattr(s.agent, "run", run)
    monkeypatch.setattr(
        s,
        "_record_turn",
        lambda *_args, **kwargs: record_kwargs.update(kwargs),
    )

    assert s.ask("public message", trusted=False) == "safe"
    assert run_kwargs["blocked_tools"]
    assert record_kwargs["review_harness"] is False


def test_build_warm_picks_codex_for_codex_provider(tmp_path, monkeypatch):
    from birkin.codex_session import CodexAppServerSession
    s = _session(tmp_path, monkeypatch, provider="codex-cli",
                 model="gpt-5.5", repl_warm_session=True)
    w = s._build_warm()                                 # constructor: no spawn
    assert isinstance(w, CodexAppServerSession)
    assert w.preamble                                   # persona/memory rides it
    assert w.network_access is False
    w.close()


def test_warm_fixed_prompt_excludes_mutable_working_state(
        tmp_path, monkeypatch):
    from birkin import harness

    session_id = "warm-fixed"
    s = _session(
        tmp_path,
        monkeypatch,
        session_id=session_id,
        repl_warm_session=True,
    )
    harness.update_working(
        session_id,
        decisions=["MUTABLE-WORKING-SENTINEL"],
    )

    warm = s._build_warm()
    fixed = getattr(warm, "append_system_prompt", None)
    if fixed is None:
        fixed = getattr(warm, "preamble", "")

    assert "MUTABLE-WORKING-SENTINEL" not in fixed
    warm.close()
