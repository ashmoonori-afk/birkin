"""`birkin harness` — show / history / rollback / export / refine.

Everything runs against the isolated BIRKIN_HOME from conftest, so the ledger
these tests write is a throwaway one.
"""

from __future__ import annotations

import json
import subprocess
import sys

from birkin import cli, harness


def _seed(title: str = "Test note", scope: str = "global",
          session_id: str | None = None) -> dict:
    return harness.apply(
        harness.load(scope, session_id=session_id),
        {"summary": f"learned about {title}",
         "rationale": "the user corrected me twice",
         "expectedOutcome": "fewer repeats",
         "edits": [{"action": "create", "kind": "memory", "title": title,
                    "content": "remember this"}]},
        scope=scope,
        session_id=session_id,
    )


# ---------------- show ----------------

def test_show_empty_is_friendly_and_exits_zero(capsys):
    rc = cli.main(["harness", "show"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip()
    assert "Traceback" not in out


def test_show_renders_the_block(capsys):
    _seed()
    rc = cli.main(["harness", "show"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Harness" in out and "Test note" in out


def test_show_scope_local_is_separate_from_global(capsys):
    _seed("Local only", scope="local")
    assert cli.main(["harness", "show", "--scope", "local"]) == 0
    assert "Local only" in capsys.readouterr().out
    assert cli.main(["harness", "show", "--scope", "global"]) == 0
    assert "Local only" not in capsys.readouterr().out


def test_show_local_selects_an_explicit_session(capsys):
    _seed("Alpha only", scope="local", session_id="alpha")
    _seed("Beta only", scope="local", session_id="beta")

    assert cli.main([
        "harness", "show", "--scope", "local", "--session-id", "alpha",
    ]) == 0
    output = capsys.readouterr().out
    assert "Alpha only" in output
    assert "Beta only" not in output


# ---------------- history ----------------

def test_history_empty_is_friendly_and_exits_zero(capsys):
    rc = cli.main(["harness", "history"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip()
    assert "Traceback" not in out


def test_history_lists_id_time_and_changes(capsys):
    event = _seed()
    rc = cli.main(["harness", "history"])
    out = capsys.readouterr().out
    assert rc == 0
    assert event["id"] in out
    assert event["created_at"] in out
    assert "create memory:test_note" in out


def test_history_limit_flag_trims_output(capsys):
    _seed("First note")
    second = _seed("Second note")
    rc = cli.main(["harness", "history", "-n", "1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert second["id"] in out
    assert len(out.strip().splitlines()) == 1


# ---------------- rollback ----------------

def test_rollback_restores_and_reports(capsys):
    event = _seed()
    assert "test_note" in harness.load()["entries"]["memory"]

    rc = cli.main(["harness", "rollback", event["id"]])
    out = capsys.readouterr().out
    assert rc == 0
    assert event["id"] in out
    assert "test_note" not in harness.load()["entries"]["memory"]


def test_rollback_unknown_id_exits_one_without_traceback(capsys):
    rc = cli.main(["harness", "rollback", "rf_nope_0000"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "rf_nope_0000" in (captured.out + captured.err)
    assert "Traceback" not in (captured.out + captured.err)


# ---------------- export ----------------

def test_export_writes_state_json(tmp_path, capsys):
    _seed()
    target = tmp_path / "out" / "harness.json"
    rc = cli.main(["harness", "export", str(target)])
    out = capsys.readouterr().out
    assert rc == 0
    assert str(target) in out
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "test_note" in data["entries"]["memory"]


def test_export_without_a_path_errors(capsys):
    rc = cli.main(["harness", "export"])
    assert rc == 1
    assert "path" in capsys.readouterr().out


# ---------------- refine ----------------

def test_refine_is_honest_about_where_proposals_come_from(capsys):
    rc = cli.main(["harness", "refine", "be", "terser"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "morpheus" in out.lower()


def test_refine_accepts_the_global_flag(capsys):
    rc = cli.main(["harness", "refine", "--global"])
    assert rc == 0
    assert capsys.readouterr().out.strip()


# ---------------- the argparse surface is real ----------------

def test_harness_help_runs_as_a_real_subcommand():
    proc = subprocess.run(
        [sys.executable, "-m", "birkin", "harness", "--help"],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    for action in ("show", "history", "rollback", "export", "refine"):
        assert action in proc.stdout
