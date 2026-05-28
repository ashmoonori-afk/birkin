"""Cross-platform scheduler daemon.

A plain Python loop (no OS cron dependency) that:
- runs the Morpheus self-improvement routine at ``morpheus_hour:morpheus_minute``
  (legacy: ``nightly_hour``/``nightly_minute``),
- fires due daily cron jobs,
- writes a heartbeat/status file for the dashboard.

Optional OS-native registration (``install_os_schedule``) adds a real
crontab/Task Scheduler entry so the routine survives without a long-running
daemon — offered as an opt-in, per ADR-008.
"""

from __future__ import annotations

import atexit
import signal
import subprocess
import sys
import time

from .proc import shell_argv
from datetime import datetime, timedelta
from typing import Any

from . import config, cron, store

_POLL_SECONDS = 30


def _morpheus_hour(cfg: dict[str, Any]) -> int:
    """Read the configured Morpheus hour, honoring the legacy ``nightly_hour``
    key so existing config.json files keep working unchanged."""
    return int(cfg.get("morpheus_hour", cfg.get("nightly_hour", 4)))


def _morpheus_minute(cfg: dict[str, Any]) -> int:
    return int(cfg.get("morpheus_minute", cfg.get("nightly_minute", 0)))


def _next_morpheus(cfg: dict[str, Any], after: datetime) -> datetime:
    target = after.replace(hour=_morpheus_hour(cfg),
                           minute=_morpheus_minute(cfg),
                           second=0, microsecond=0)
    if target <= after:
        target += timedelta(days=1)
    return target


# Legacy name kept for tests / external callers that already import it.
_next_nightly = _next_morpheus


def run_daemon() -> int:
    cfg = config.load_config()
    next_morpheus = _next_morpheus(cfg, datetime.now())
    print(f"birkin daemon started. Next Morpheus run at "
          f"{next_morpheus:%Y-%m-%d %H:%M}. Ctrl-C to stop.")
    _write_status(cfg, next_morpheus, running=True)

    # Clear the on-disk status on a graceful stop OR a SIGTERM (so the
    # dashboard never claims a dead daemon is still running).
    atexit.register(store.clear_status)
    try:
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    except (AttributeError, ValueError):
        pass  # not all platforms / contexts support setting handlers

    try:
        while True:
            now = datetime.now()

            if now >= next_morpheus:
                print(f"[{now:%H:%M}] running Morpheus routine…")
                try:
                    from .morpheus import run_once
                    run_once()
                except Exception as exc:  # never kill the daemon
                    store.save_run("morpheus", f"daemon morpheus error: {exc}")
                next_morpheus = _next_morpheus(cfg, now + timedelta(minutes=1))

            for job in cron.due_jobs(now):
                print(f"[{now:%H:%M}] running cron job '{job.get('name')}'…")
                _run_job(job)
                cron.mark_ran(job["id"])

            _write_status(cfg, next_morpheus, running=True)
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
            proc = subprocess.run(shell_argv(value), capture_output=True,
                                  text=True, errors="replace", timeout=600)
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


def _write_status(cfg: dict[str, Any], next_morpheus: datetime, running: bool) -> None:
    # Emit both ``next_morpheus`` / ``morpheus_hour`` (canonical) and the
    # legacy ``next_nightly`` / ``nightly_hour`` keys so dashboards / tests
    # built against the old names keep working.
    iso = next_morpheus.isoformat(timespec="seconds")
    hour = _morpheus_hour(cfg)
    store.write_status({
        "daemon": running,
        "next_morpheus": iso,
        "next_nightly": iso,
        "morpheus_hour": hour,
        "nightly_hour": hour,
        "cron_jobs": [
            {"id": j["id"], "name": j.get("name"),
             "at": f"{int(j.get('hour', 0)):02d}:{int(j.get('minute', 0)):02d}",
             "type": j.get("type"), "enabled": j.get("enabled", True),
             "last_run": j.get("last_run")}
            for j in cron.load_jobs()],
    })


# -- optional OS-native registration --------------------------------------

def install_os_schedule() -> int:
    """Register a daily OS task that runs `birkin morpheus`.

    Uses Task Scheduler on Windows and crontab elsewhere. Opt-in.
    The task / crontab entry name stays ``birkin-nightly`` so an existing
    installation isn't duplicated when this is re-run after the rename.
    """
    cfg = config.load_config()
    hour, minute = _morpheus_hour(cfg), _morpheus_minute(cfg)
    py = sys.executable

    if sys.platform.startswith("win"):
        cmd = f'"{py}" -m birkin morpheus'
        args = ["schtasks", "/Create", "/SC", "DAILY", "/TN", "birkin-nightly",
                "/ST", f"{hour:02d}:{minute:02d}", "/TR", cmd, "/F"]
        try:
            # schtasks prints in the Windows OEM codepage (e.g. cp949 on Korean
            # Windows); decode with "oem" so the message is readable.
            proc = subprocess.run(args, capture_output=True, text=True,
                                  encoding="oem", errors="replace")
        except FileNotFoundError:
            print("schtasks not available on this system.")
            return 1
        print(proc.stdout or proc.stderr)
        return proc.returncode

    # POSIX: append a crontab line if not present.
    line = f"{minute} {hour} * * * {py} -m birkin morpheus  # birkin-nightly"
    try:
        existing = subprocess.run(["crontab", "-l"], capture_output=True,
                                  text=True, errors="replace").stdout
    except FileNotFoundError:
        print("crontab not available on this system.")
        return 1
    if "birkin-nightly" in existing:
        print("birkin-nightly crontab entry already present.")
        return 0
    new = (existing.rstrip("\n") + "\n" + line + "\n").lstrip("\n")
    proc = subprocess.run(["crontab", "-"], input=new, text=True,
                          capture_output=True, errors="replace")
    if proc.returncode == 0:
        print(f"Installed crontab entry: {line}")
    else:
        print(proc.stderr)
    return proc.returncode
