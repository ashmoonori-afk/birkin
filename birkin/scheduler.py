"""Cross-platform scheduler daemon.

A plain Python loop (no OS cron dependency) that:
- runs the nightly self-improvement routine at ``nightly_hour:nightly_minute``,
- fires due daily cron jobs,
- writes a heartbeat/status file for the dashboard.

Optional OS-native registration (``install_os_schedule``) adds a real
crontab/Task Scheduler entry so the routine survives without a long-running
daemon — offered as an opt-in, per ADR-008.
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timedelta
from typing import Any

from . import config, cron, store

_POLL_SECONDS = 30


def _next_nightly(cfg: dict[str, Any], after: datetime) -> datetime:
    target = after.replace(hour=int(cfg.get("nightly_hour", 4)),
                           minute=int(cfg.get("nightly_minute", 0)),
                           second=0, microsecond=0)
    if target <= after:
        target += timedelta(days=1)
    return target


def run_daemon() -> int:
    cfg = config.load_config()
    next_nightly = _next_nightly(cfg, datetime.now())
    print(f"birkin daemon started. Next nightly at {next_nightly:%Y-%m-%d %H:%M}. "
          f"Ctrl-C to stop.")
    _write_status(cfg, next_nightly, running=True)

    try:
        while True:
            now = datetime.now()

            if now >= next_nightly:
                print(f"[{now:%H:%M}] running nightly routine…")
                try:
                    from .nightly import run_once
                    run_once()
                except Exception as exc:  # never kill the daemon
                    store.save_run("nightly", f"daemon nightly error: {exc}")
                next_nightly = _next_nightly(cfg, now + timedelta(minutes=1))

            for job in cron.due_jobs(now):
                print(f"[{now:%H:%M}] running cron job '{job.get('name')}'…")
                _run_job(job)
                cron.mark_ran(job["id"])

            _write_status(cfg, next_nightly, running=True)
            time.sleep(_POLL_SECONDS)
    except KeyboardInterrupt:
        print("\ndaemon stopping…")
    finally:
        store.clear_status()
    return 0


def _run_job(job: dict[str, Any]) -> None:
    jtype = job.get("type", "prompt")
    value = job.get("value", "")
    try:
        if jtype == "shell":
            proc = subprocess.run(value, shell=True, capture_output=True,
                                  text=True, timeout=600)
            out = (proc.stdout or "") + (proc.stderr or "")
            store.save_run("cron", f"[{job.get('name')}] exit {proc.returncode}",
                           {"output": out[:2000], "job": job["id"]})
        elif jtype == "prompt":
            from .runtime import ConfigError, build_session
            try:
                session = build_session()
            except ConfigError as exc:
                store.save_run("cron", f"[{job.get('name')}] skipped: {exc}")
                return
            summary = session.ask(value)
            store.save_run("cron", f"[{job.get('name')}] {summary[:200]}",
                           {"summary": summary, "job": job["id"]})
    except Exception as exc:
        store.save_run("cron", f"[{job.get('name')}] error: {exc}")


def _write_status(cfg: dict[str, Any], next_nightly: datetime, running: bool) -> None:
    store.write_status({
        "daemon": running,
        "next_nightly": next_nightly.isoformat(timespec="seconds"),
        "nightly_hour": cfg.get("nightly_hour", 4),
        "cron_jobs": [
            {"id": j["id"], "name": j.get("name"),
             "at": f"{int(j.get('hour', 0)):02d}:{int(j.get('minute', 0)):02d}",
             "type": j.get("type"), "enabled": j.get("enabled", True),
             "last_run": j.get("last_run")}
            for j in cron.load_jobs()],
    })


# -- optional OS-native registration --------------------------------------

def install_os_schedule() -> int:
    """Register a daily OS task that runs `birkin nightly`.

    Uses Task Scheduler on Windows and crontab elsewhere. Opt-in.
    """
    cfg = config.load_config()
    hour, minute = int(cfg.get("nightly_hour", 4)), int(cfg.get("nightly_minute", 0))
    py = sys.executable

    if sys.platform.startswith("win"):
        cmd = f'"{py}" -m birkin nightly'
        args = ["schtasks", "/Create", "/SC", "DAILY", "/TN", "birkin-nightly",
                "/ST", f"{hour:02d}:{minute:02d}", "/TR", cmd, "/F"]
        try:
            proc = subprocess.run(args, capture_output=True, text=True)
        except FileNotFoundError:
            print("schtasks not available on this system.")
            return 1
        print(proc.stdout or proc.stderr)
        return proc.returncode

    # POSIX: append a crontab line if not present.
    line = f"{minute} {hour} * * * {py} -m birkin nightly  # birkin-nightly"
    try:
        existing = subprocess.run(["crontab", "-l"], capture_output=True,
                                  text=True).stdout
    except FileNotFoundError:
        print("crontab not available on this system.")
        return 1
    if "birkin-nightly" in existing:
        print("birkin-nightly crontab entry already present.")
        return 0
    new = (existing.rstrip("\n") + "\n" + line + "\n").lstrip("\n")
    proc = subprocess.run(["crontab", "-"], input=new, text=True,
                          capture_output=True)
    if proc.returncode == 0:
        print(f"Installed crontab entry: {line}")
    else:
        print(proc.stderr)
    return proc.returncode
