"""The pre-run picker and the three signals it shows instead of dollars.

birkin usually drives claude-cli or codex-cli, where a per-token price does
not exist, so a price tag would be wrong on most runs and stale on the rest.
These tests pin what replaced it: a relative weight that cannot go stale,
a duration measured on this machine, and a budget share that only appears
when there is a budget to spend.
"""

from __future__ import annotations

import pytest

from birkin import ui
from birkin.moirai import journal, picker
from birkin.moirai.bindings import Binding


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    yield tmp_path


def _b(role="w", provider="codex", model="gpt-5.6-sol"):
    return {role: Binding(role, provider, model, "meta")}


# ---------------- weight ---------------------------------------------------

@pytest.mark.parametrize("model,glyph", [
    ("opus", "●●●"), ("gpt-5.6-sol", "●●●"),
    ("sonnet", "●●○"),
    ("haiku", "●○○"), ("gpt-5.3-codex-spark", "●○○"), ("llama3", "●○○"),
])
def test_weight_grades_follow_the_model_family(model, glyph):
    assert picker.weight_glyph(model) == glyph


def test_an_unknown_model_grades_as_standard_rather_than_guessing_extreme():
    assert picker.weight_glyph("something-new-2027") == "●●○"


def test_weight_carries_no_price():
    """A relative grade is the whole point — it cannot go stale on a reprice."""
    import inspect
    src = inspect.getsource(picker)
    assert "$" not in src.replace("$1", "")
    assert "USD" not in src and "MTok" not in src


# ---------------- duration -------------------------------------------------

def test_duration_is_seeded_before_anything_has_been_measured():
    est = picker.estimate(Binding("w", "codex", "gpt-5.6-sol", "meta"), 2)
    assert est["measured"] is False
    assert est["seconds"] == picker.SEEDED_SECONDS["codex"]
    assert est["total_seconds"] == est["seconds"] * 2


def test_duration_switches_to_this_machine_once_it_has_run(monkeypatch):
    monkeypatch.setattr(journal, "observed",
                        lambda p, m: {"seconds": 42.0, "tokens": 100.0,
                                      "n": 3.0})
    est = picker.estimate(Binding("w", "codex", "x", "meta"), 2)
    assert est["measured"] is True and est["seconds"] == 42.0


def test_an_estimate_is_marked_but_a_measurement_is_not(monkeypatch):
    unmeasured = picker.plan_table(_b(), {"w": 1}, {})
    assert "~" in unmeasured

    monkeypatch.setattr(journal, "observed",
                        lambda p, m: {"seconds": 9.0, "tokens": 10.0, "n": 1.0})
    measured = picker.plan_table(_b(), {"w": 1}, {})
    assert "9초 ×1" in measured and "~9초" not in measured


def test_a_role_that_is_never_called_shows_a_dash_not_a_number():
    table = picker.plan_table(_b(), {}, {})
    assert "—" in table


# ---------------- budget footprint ----------------------------------------

def test_the_budget_column_hides_itself_when_no_cap_is_set():
    assert picker.budget_footprint(5000, {}) is None
    assert "예산" not in picker.plan_table(_b(), {"w": 2}, {})


def test_the_budget_column_appears_and_scales_with_the_cap():
    share = picker.budget_footprint(500, {"budget_tokens_daily": 1000})
    assert share == pytest.approx(0.5)
    table = picker.plan_table(_b(), {"w": 2}, {"budget_tokens_daily": 100000})
    assert "일일 예산의" in table


def test_a_run_that_would_exhaust_the_budget_says_so_before_it_starts():
    table = picker.plan_table(_b(), {"w": 50}, {"budget_tokens_daily": 100})
    assert "넘길 수 있습니다" in table


# ---------------- table rendering -----------------------------------------

def test_the_table_is_aligned_in_display_cells_not_characters():
    """Korean headers and ● glyphs are wide; len()-based padding drifts."""
    bindings = {"drafter": Binding("drafter", "codex", "gpt-5.6-sol", "meta"),
                "critic": Binding("critic", "claude", "haiku", "meta")}
    lines = picker.plan_table(bindings, {"drafter": 1, "critic": 3},
                              {}).splitlines()
    body = [ln for ln in lines if "→" in ln]
    widths = {ui.cell_width(ln.split("●")[0]) for ln in body}
    assert len(widths) == 1, f"binding column is ragged: {widths}"


def test_confirm_reads_yes_no_and_save(monkeypatch):
    for typed, expect in [("", "y"), ("y", "y"), ("n", "n"), ("no", "n"),
                          ("s", "s"), ("저장", "s")]:
        monkeypatch.setattr("builtins.input", lambda _p, t=typed: t)
        assert picker.confirm() == expect


def test_confirm_treats_an_unreadable_answer_as_no(monkeypatch):
    def boom(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", boom)
    assert picker.confirm() == "n"


def test_saving_bindings_writes_them_as_the_standing_default(tmp_path):
    from birkin import config
    picker.save_bindings(_b("critic", "claude", "opus"), {})
    assert config.load_config()["moirai_roles"]["critic"] == "claude:opus"


# ---------------- when not to ask -----------------------------------------

def test_defaults_flag_skips_the_picker():
    import argparse

    from birkin.moirai.cli import _should_ask
    assert _should_ask(argparse.Namespace(defaults=True)) is False


def test_a_non_interactive_surface_never_prompts(monkeypatch):
    import argparse

    from birkin.moirai import cli as moirai_cli
    monkeypatch.setattr("birkin.inline_complete._is_interactive",
                        lambda: False)
    assert moirai_cli._should_ask(argparse.Namespace(defaults=False)) is False


def test_the_picker_offers_last_run_and_script_default_without_duplicates(
        monkeypatch):
    seen = {}

    def fake_select(title, options, default=0):
        seen["options"] = list(options)
        return 0

    monkeypatch.setattr(picker.menu, "select", fake_select)
    roles = {"critic": {"default": "claude:haiku", "hint": "반박"}}
    resolved = {"critic": Binding("critic", "claude", "haiku", "meta")}
    got = picker.choose(roles, resolved, cfg={},
                        last={"critic": "claude:opus"})
    assert got == {"critic": "claude:haiku"}
    labels = " ".join(seen["options"])
    assert "claude:opus" in labels and "다른 모델 고르기" in labels
    assert labels.count("claude:haiku") == 1, "the same spec offered twice"


def test_cancelling_the_picker_cancels_the_run(monkeypatch):
    monkeypatch.setattr(picker.menu, "select",
                        lambda title, options, default=0: None)
    assert picker.choose({"w": {"default": "codex:x"}},
                         {"w": Binding("w", "codex", "x", "meta")},
                         cfg={}) is None


# ---------------- the picker is actually reached --------------------------

def _cmd_args(**kw):
    import argparse
    base = dict(script="", bind=[], args="", defaults=False, bind_save=False)
    base.update(kw)
    return argparse.Namespace(**base)


def _wf(tmp_path):
    p = tmp_path / "w.py"
    p.write_text('''
meta = {"name": "picked", "roles": {"w": {"default": "codex:x"}}}

def main(m):
    return m.agent("hi", role="w")
''', encoding="utf-8")
    return p


def test_cmd_run_actually_calls_the_picker_when_interactive(tmp_path,
                                                            monkeypatch):
    """Regression: the picker was written, imported, and never called.

    Everything it does is unit-tested, the README describes it, and none of
    that noticed that cmd_run went straight past it — a static audit found it.
    Assert reachability, not existence.
    """
    from birkin.moirai import cli as moirai_cli

    called = {}
    monkeypatch.setattr(moirai_cli, "_should_ask", lambda args: True)
    def fake_choose(*a, **k):
        called["choose"] = True
        return {"w": "codex:x"}

    def fake_confirm(*a, **k):
        called["confirm"] = "y"
        return "y"

    monkeypatch.setattr(moirai_cli.picker, "choose", fake_choose)
    monkeypatch.setattr(moirai_cli.picker, "confirm", fake_confirm)
    monkeypatch.setattr(moirai_cli, "run_script",
                        lambda *a, **k: {"status": "completed", "agents": 1,
                                         "cache_hits": 0, "seconds": 0.1,
                                         "tokens": 1, "run_id": "r",
                                         "result": None})
    assert moirai_cli.cmd_run(_cmd_args(script=str(_wf(tmp_path)))) == 0
    assert called.get("choose") and called.get("confirm") == "y"


def test_declining_at_the_confirmation_does_not_run_anything(tmp_path,
                                                             monkeypatch):
    from birkin.moirai import cli as moirai_cli

    ran = []
    monkeypatch.setattr(moirai_cli, "_should_ask", lambda args: True)
    monkeypatch.setattr(moirai_cli.picker, "choose",
                        lambda *a, **k: {"w": "codex:x"})
    monkeypatch.setattr(moirai_cli.picker, "confirm", lambda *a, **k: "n")
    monkeypatch.setattr(moirai_cli, "run_script",
                        lambda *a, **k: ran.append(1))
    assert moirai_cli.cmd_run(_cmd_args(script=str(_wf(tmp_path)))) == 130
    assert not ran, "declining still started the workflow"


def test_cancelling_the_picker_stops_before_the_plan_table(tmp_path,
                                                           monkeypatch):
    from birkin.moirai import cli as moirai_cli

    ran = []
    monkeypatch.setattr(moirai_cli, "_should_ask", lambda args: True)
    monkeypatch.setattr(moirai_cli.picker, "choose", lambda *a, **k: None)
    monkeypatch.setattr(moirai_cli, "run_script",
                        lambda *a, **k: ran.append(1))
    assert moirai_cli.cmd_run(_cmd_args(script=str(_wf(tmp_path)))) == 130
    assert not ran


def test_defaults_runs_without_asking_but_still_prints_the_plan(
        tmp_path, monkeypatch, capsys):
    from birkin.moirai import cli as moirai_cli

    monkeypatch.setattr(moirai_cli, "run_script",
                        lambda *a, **k: {"status": "completed", "agents": 1,
                                         "cache_hits": 0, "seconds": 0.1,
                                         "tokens": 1, "run_id": "r",
                                         "result": None})

    def boom(*a, **k):
        raise AssertionError("--defaults must not prompt")

    monkeypatch.setattr(moirai_cli.picker, "choose", boom)
    monkeypatch.setattr(moirai_cli.picker, "confirm", boom)
    assert moirai_cli.cmd_run(
        _cmd_args(script=str(_wf(tmp_path)), defaults=True)) == 0
    assert "확정 바인딩" in capsys.readouterr().out


def test_bind_save_persists_even_without_the_prompt(tmp_path, monkeypatch):
    from birkin import config
    from birkin.moirai import cli as moirai_cli

    monkeypatch.setattr(moirai_cli, "run_script",
                        lambda *a, **k: {"status": "completed", "agents": 1,
                                         "cache_hits": 0, "seconds": 0.1,
                                         "tokens": 1, "run_id": "r",
                                         "result": None})
    moirai_cli.cmd_run(_cmd_args(script=str(_wf(tmp_path)), defaults=True,
                                 bind_save=True))
    assert config.load_config()["moirai_roles"]["w"] == "codex:x"
