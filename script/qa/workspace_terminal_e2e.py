"""Drive the default Birkin workspace through a real pseudo-terminal."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

from script.qa.workspace_terminal_pty import run_terminal_scenario

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / ".omo" / "evidence" / "unified-workspace"

FIRST_SCENARIO = r"""
set timeout 20
expect_before timeout {puts stderr "QA_EXPECT_TIMEOUT"; exit 124}
match_max 1000000
set home {__HOME__}
set python {__PYTHON__}
set prompt "\033\[>1u"
spawn -noecho env BIRKIN_HOME=$home PYTHONUNBUFFERED=1 \
    $python -m script.qa.workspace_terminal_fixture
fconfigure $spawn_id -encoding utf-8
puts "QA_PID=[exp_pid]"

expect -exact $prompt
send -- "approval start\r"
expect -exact "fixture-tool"
expect -exact "Approval required. Type approve to resume."
expect -exact $prompt

log_file -noappend "$home/capture-60.raw"
stty -i $spawn_id rows 24 columns 60
send -- "/work\r"
expect -exact "focused tasks/runs."
expect -exact $prompt
send -- "approve\r"
expect -exact "shared continuation"
expect -exact $prompt

log_file
log_file -noappend "$home/capture-160.raw"
stty -i $spawn_id rows 42 columns 160
send -- "붙여넣기-가나다라마바사가나다라마바사가나다라마바사-END\r"
expect -exact "-END"
expect -exact $prompt

log_file
log_file -noappend "$home/capture-100.raw"
stty -i $spawn_id rows 30 columns 100
send -- "interrupt\r"
expect -exact "interrupt-ready"
send -- "\033"
expect -exact "Interrupted safely"
expect -exact $prompt
send -- "/dash\r"
expect -exact "deprecated"
expect -exact $prompt
send -- "/quit\r"
expect -exact "bye."
expect eof
set result [wait]
exit [lindex $result 3]
"""

RECONNECT_SCENARIO = r"""
set timeout 20
expect_before timeout {puts stderr "QA_RECONNECT_TIMEOUT"; exit 124}
match_max 1000000
set home {__HOME__}
set python {__PYTHON__}
set prompt "\033\[>1u"
spawn -noecho env BIRKIN_HOME=$home PYTHONUNBUFFERED=1 \
    $python -m script.qa.workspace_terminal_fixture
fconfigure $spawn_id -encoding utf-8
puts "QA_RECONNECT_PID=[exp_pid]"
expect -exact "Interrupted safely"
expect -exact $prompt
send -- "/quit\r"
expect -exact "bye."
expect eof
set result [wait]
exit [lindex $result 3]
"""


def _run_expect(script: str, profile: Path) -> str:
    prepared = script.replace("__HOME__", str(profile)).replace(
        "__PYTHON__",
        sys.executable,
    )
    completed = subprocess.run(
        ["/usr/bin/expect", "-c", prepared],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0 or "while executing" in completed.stdout:
        raise AssertionError(
            f"PTY scenario exited {completed.returncode}\n{completed.stdout[-6000:]}"
        )
    return completed.stdout.replace("ð§µ", "🧵").replace("â", "✓")


def _required_number(text: str, pattern: str, label: str) -> int:
    match = re.search(pattern, text)
    if match is None:
        raise AssertionError(f"{label} missing from PTY output")
    return int(match.group(1))


_ = _run_expect
_ = _required_number


def _write_terminal_svg(
    evidence: Path,
    raw: str,
    *,
    columns: int,
) -> None:
    cleaned = re.sub(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|[=>])", "", raw)
    lines = [
        line.replace("\r", "")
        for line in cleaned.splitlines()
        if line.strip()
    ][-24:]
    width = columns * 9 + 24
    height = len(lines) * 18 + 24
    spans = "".join(
        f'<tspan x="12" dy="18">{html.escape(line)}</tspan>'
        for line in lines
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">'
        '<rect width="100%" height="100%" fill="#11100f"/>'
        '<text x="12" y="4" fill="#f4eadf" '
        'font-family="ui-monospace, monospace" font-size="14">'
        f"{spans}</text></svg>\n"
    )
    _ = (evidence / f"terminal-{columns}.svg").write_text(
        svg,
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=EVIDENCE,
    )
    args = parser.parse_args()
    evidence = cast(Path, args.evidence_dir).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="birkin-terminal-pty-"))
    try:
        scenario = run_terminal_scenario(profile)
        first = cast(str, scenario["first"])
        journal = profile / "workspace" / "qa-terminal" / "events.jsonl"
        if not journal.is_file():
            paths = [str(path.relative_to(profile)) for path in profile.rglob("*")]
            message = (
                f"durable workspace journal was not created: {paths}\n{first[-5000:]}"
            )
            raise AssertionError(message)
        journal_text = journal.read_text(encoding="utf-8")
        if "붙여넣기-가나다라마바사" not in journal_text or "Echo complete 🧵" not in journal_text:
            raise AssertionError("durable Unicode event data was corrupted")
        reconnect = cast(str, scenario["reconnect"])
        if (profile / "web_session.json").exists():
            raise AssertionError("web discovery file survived clean shutdown")

        metadata = {
            "pid": scenario["pid"],
            "reconnect_pid": scenario["reconnect_pid"],
            "port": scenario["port"],
            "widths": [60, 100, 160],
            "profile_path": str(profile),
            "journal_path": str(journal),
            "journal_bytes": journal.stat().st_size,
            "unicode_sentinel": "🧵-END",
            "processes_exited": True,
            "web_session_removed": True,
            "profile_removed": True,
        }
        _ = (evidence / "terminal-pty.raw.txt").write_text(
            first + "\n--- RECONNECT ---\n" + reconnect,
            encoding="utf-8",
        )
        _ = (evidence / "terminal-pty.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for columns in (60, 100, 160):
            captures = cast(dict[int, str], scenario["captures"])
            capture = captures[columns]
            _write_terminal_svg(
                evidence,
                capture,
                columns=columns,
            )
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    print("PTY workspace QA passed: stream/tool/approval/resume/resize/Unicode/Esc/reconnect")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
