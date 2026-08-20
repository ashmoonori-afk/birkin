"""The slash-command surface: one command per job, no dead aliases.

``/dash`` was a deprecated alias for ``/work``; it is gone. ``/model`` and
``/models`` did the same job through two names and are now one command.
"""

from __future__ import annotations

import types

import pytest

import birkin.repl  # noqa: F401  — importing populates the registry
from birkin import slashcommands as sc


def _session(**kw):
    return types.SimpleNamespace(**kw)


# -- /dash is gone ---------------------------------------------------------

@pytest.mark.parametrize("name", ["dash", "dashboard"])
def test_the_dash_command_and_its_alias_are_gone(name: str) -> None:
    assert name not in sc._REGISTRY
    assert name not in sc._ALIASES


def test_dispatching_dash_reports_an_unknown_command(capsys) -> None:
    focused: list[str] = []
    session = _session(workspace_focus=focused.append)

    assert sc.dispatch(session, "/dash") == "continue"

    out = capsys.readouterr().out
    assert "Unknown command /dash" in out
    assert focused == [], "a removed command still focused a panel"


def test_work_is_the_only_workbench_command() -> None:
    assert "work" in sc._REGISTRY
    assert sc._ALIASES.get("workbench") == "work"


# -- /model and /models are one command ------------------------------------

def test_models_is_an_alias_of_model_not_a_second_command() -> None:
    assert "models" not in sc._REGISTRY, "/models is still a separate command"
    assert sc._ALIASES.get("models") == "model"


def test_model_with_an_argument_sets_the_model(monkeypatch) -> None:
    chosen: list[str] = []
    monkeypatch.setattr(sc, "_set_model", lambda session, arg: chosen.append(arg))
    sc.dispatch(_session(cfg={"model": "old"}), "/model gpt-5.6")
    assert chosen == ["gpt-5.6"]


def test_models_alias_with_an_argument_sets_the_model(monkeypatch) -> None:
    chosen: list[str] = []
    monkeypatch.setattr(sc, "_set_model", lambda session, arg: chosen.append(arg))
    sc.dispatch(_session(cfg={"model": "old"}), "/models gpt-5.6")
    assert chosen == ["gpt-5.6"]


# -- the surface as a whole ------------------------------------------------

def test_every_command_and_alias_is_reachable_and_unique() -> None:
    assert not (set(sc._ALIASES) & set(sc._REGISTRY)), (
        "an alias shadows a real command name"
    )
    for alias, target in sc._ALIASES.items():
        assert target in sc._REGISTRY, f"/{alias} points at missing /{target}"


# -- the merged commands ---------------------------------------------------

REMOVED = ["skill", "reload", "remember", "vault", "save", "load",
           "restart-gateway", "hard-restart", "personality"]


@pytest.mark.parametrize("name", REMOVED)
def test_merged_away_commands_are_gone(name: str) -> None:
    assert name not in sc._REGISTRY, f"/{name} is still its own command"


def test_bare_model_always_opens_the_picker(monkeypatch, capsys) -> None:
    """hermes parity: /model picks, it never just prints the current model."""
    from birkin import models as models_mod

    opened: list[bool] = []
    monkeypatch.setattr(models_mod, "pick_interactive",
                        lambda cfg: opened.append(True) or None)
    sc.dispatch(_session(cfg={"model": "claude-sonnet-4-6"}), "/model")

    assert opened == [True], "bare /model did not open the picker"
    assert "claude-sonnet-4-6" not in capsys.readouterr().out


# A1 -- /restart [--hard]

@pytest.mark.parametrize(("arg", "wire"), [
    ("", "/restart-gateway"),
    ("--hard", "/hard-restart"),
])
def test_restart_sends_the_gateway_wire_string(monkeypatch, arg, wire) -> None:
    sent: list[str] = []
    monkeypatch.setattr(sc, "_gateway_post",
                        lambda cfg, text: sent.append(text) or "ok")
    sc.dispatch(_session(cfg={}), f"/restart {arg}".strip())
    assert sent == [wire]


def test_restart_rejects_an_unknown_flag(capsys) -> None:
    sc.dispatch(_session(cfg={}), "/restart --sideways")
    assert "usage: /restart" in capsys.readouterr().out


# A2 -- /persona

def test_persona_sets_a_preset(monkeypatch) -> None:
    from birkin import persona
    written: list[str] = []
    monkeypatch.setattr(persona, "write_soul", written.append)
    sc.dispatch(_session(cfg={}), "/persona concise")
    assert written and written[0] == persona.PRESETS["concise"]


def test_persona_still_shows_the_path_and_resets(monkeypatch, capsys) -> None:
    from birkin import persona
    reset: list[bool] = []
    monkeypatch.setattr(persona, "seed_default",
                        lambda force=False: reset.append(force))
    monkeypatch.setattr(persona, "soul_path", lambda: "/x/SOUL.md")
    sc.dispatch(_session(cfg={}), "/persona path")
    assert "/x/SOUL.md" in capsys.readouterr().out
    sc.dispatch(_session(cfg={}), "/persona reset")
    assert reset == [True]


def test_soul_is_still_an_alias_of_persona() -> None:
    assert sc._ALIASES.get("soul") == "persona"


# B1 -- /skills [name|reload]

def test_skills_lists_shows_and_reloads(monkeypatch, capsys) -> None:
    reloaded: list[bool] = []
    skills = types.SimpleNamespace(
        index=lambda: "INDEX",
        get=lambda name: types.SimpleNamespace(full=lambda: f"FULL:{name}"),
        reload=lambda: reloaded.append(True),
        skills=[1, 2])
    session = _session(skills=skills)

    sc.dispatch(session, "/skills")
    assert "INDEX" in capsys.readouterr().out
    sc.dispatch(session, "/skills writing")
    assert "FULL:writing" in capsys.readouterr().out
    sc.dispatch(session, "/skills reload")
    assert reloaded == [True]


# B2 -- /memory subcommands

def test_memory_searches_saves_and_locates(capsys) -> None:
    saved: list[tuple] = []
    memory = types.SimpleNamespace(
        vault="/x/vault",
        list_notes=lambda: [1, 2, 3],
        search=lambda q: [{"title": f"hit:{q}", "snippet": "s"}],
        write_note=lambda title, body, note_type, source: saved.append((title, body)))
    session = _session(memory=memory)

    sc.dispatch(session, "/memory birkin")
    assert "hit:birkin" in capsys.readouterr().out
    sc.dispatch(session, "/memory save the sky is blue")
    assert saved and saved[0][1] == "the sky is blue"
    sc.dispatch(session, "/memory where")
    out = capsys.readouterr().out
    assert "/x/vault" in out and "3" in out


def test_memory_save_without_text_is_refused(capsys) -> None:
    memory = types.SimpleNamespace(
        vault="/x", list_notes=lambda: [], search=lambda q: [],
        write_note=lambda **kw: pytest.fail("saved an empty note"))
    sc.dispatch(_session(memory=memory), "/memory save")
    assert "remember" in capsys.readouterr().out.lower()


# B3 -- /sessions subcommands

def test_sessions_saves_and_loads(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sc.config, "sessions_dir", lambda: tmp_path)
    agent = types.SimpleNamespace(messages=[{"role": "user", "content": []}])
    session = _session(agent=agent)

    sc.dispatch(session, "/sessions save demo")
    assert (tmp_path / "demo.json").is_file()

    agent.messages = []
    sc.dispatch(session, "/sessions load demo")
    assert len(agent.messages) == 1


def test_sessions_load_without_a_name_is_refused(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sc.config, "sessions_dir", lambda: tmp_path)
    sc.dispatch(_session(agent=types.SimpleNamespace(messages=[])), "/sessions load")
    assert "name" in capsys.readouterr().out.lower()


def test_bare_sessions_still_lists(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sc.config, "sessions_dir", lambda: tmp_path)
    (tmp_path / "alpha.json").write_text("[]", encoding="utf-8")
    sc.dispatch(_session(), "/sessions")
    assert "alpha" in capsys.readouterr().out
