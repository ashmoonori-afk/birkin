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


def test_bare_model_opens_the_picker_when_interactive(monkeypatch) -> None:
    from birkin import models as models_mod

    picked = types.SimpleNamespace(id="picked-model")
    monkeypatch.setattr(sc, "_stdin_is_interactive", lambda: True)
    monkeypatch.setattr(models_mod, "pick_interactive", lambda cfg: picked)
    monkeypatch.setattr(sc.config, "save_config", lambda cfg: None)
    monkeypatch.setattr(sc, "_warn_if_key_missing", lambda session: None)

    reloaded: list[bool] = []
    session = _session(cfg={"model": "old", "provider": "anthropic"},
                       reload_client=lambda: reloaded.append(True))
    sc.dispatch(session, "/model")
    assert reloaded == [True], "the picker's choice was never applied"


def test_bare_model_only_prints_when_not_interactive(monkeypatch, capsys) -> None:
    """A gateway/telegram turn must never block on an interactive picker."""
    from birkin import models as models_mod

    def explode(cfg):
        raise AssertionError("the picker ran without a terminal")

    monkeypatch.setattr(sc, "_stdin_is_interactive", lambda: False)
    monkeypatch.setattr(models_mod, "pick_interactive", explode)

    sc.dispatch(_session(cfg={"model": "claude-sonnet-4-6"}), "/model")
    assert "claude-sonnet-4-6" in capsys.readouterr().out


# -- the surface as a whole ------------------------------------------------

def test_every_command_and_alias_is_reachable_and_unique() -> None:
    assert not (set(sc._ALIASES) & set(sc._REGISTRY)), (
        "an alias shadows a real command name"
    )
    for alias, target in sc._ALIASES.items():
        assert target in sc._REGISTRY, f"/{alias} points at missing /{target}"
