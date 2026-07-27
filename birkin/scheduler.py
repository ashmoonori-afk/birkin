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
import os
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .proc import shell_argv
from datetime import datetime, timedelta
from typing import Any

from . import config, cron, store

_POLL_SECONDS = 30
_TG_SEND = "https://api.telegram.org/bot{token}/sendMessage"


def _is_silent(text: str) -> bool:
    """hermes ``[SILENT]`` convention: a job whose output flags itself silent
    is recorded locally but never delivered — no notification fatigue when a
    monitor has nothing to report. The marker must be the FIRST token of the
    output: a substring match would let untrusted text a shell job merely
    *prints* (grepped logs, fetched pages) suppress real findings."""
    head = (text or "").strip()
    return head.startswith("[SILENT]") or head.upper().startswith("NO_REPLY")


def _send_telegram(token: str, chat_id: str, text: str) -> None:
    body = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text[:3500]}).encode()
    req = urllib.request.Request(_TG_SEND.format(token=token), data=body)
    with urllib.request.urlopen(req, timeout=15):
        pass


def _deliver(job: dict[str, Any], text: str) -> str:
    """Deliver a job's output to its Telegram chat, honoring ``[SILENT]``.

    Returns a short status recorded with the run: ``sent`` /
    ``skipped-silent`` / ``none`` (no deliver target) / ``error: …``."""
    chat = str(job.get("deliver_chat_id") or "").strip()
    if not chat:
        return "none"
    if _is_silent(text):
        return "skipped-silent"
    cfg = config.load_config()
    tg = (cfg.get("channels") or {}).get("telegram") or {}
    # Outbound targets honor the same allowlist as inbound messages — a job
    # payload must not be able to exfiltrate run output to a stranger's chat.
    allowed = [str(x) for x in (tg.get("allowed_chat_ids") or [])]
    if allowed and chat not in allowed:
        return "error: chat_id not in channels.telegram.allowed_chat_ids"
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or tg.get("token") or ""
    if not token:
        return "error: no telegram token (set TELEGRAM_BOT_TOKEN)"
    try:
        _send_telegram(token, chat, f"[{job.get('name', 'cron')}] {text}")
        return "sent"
    except Exception as exc:                    # network/HTTP — job still ran
        return f"error: {exc}"


def deliver(name: str, chat_id: str | None, text: str) -> str:
    """Public one-shot delivery to a Telegram chat, honoring the [SILENT]
    convention and the outbound allowlist — used by Morpheus for the
    morning digest (P0-3) in addition to cron jobs."""
    return _deliver({"name": name, "deliver_chat_id": chat_id or ""}, text)


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
    next_reap = datetime.now() + timedelta(hours=1)
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
                # Claim BEFORE running (atomic stamp under the cron lock) so a
                # second daemon reading the same due job can't run it too.
                if not cron.claim_if_due(job["id"], now):
                    continue
                print(f"[{now:%H:%M}] running cron job '{job.get('name')}'…")
                _run_job(job)

            if now >= next_reap and cfg.get("reaper_enabled", True):
                try:
                    from . import procreg
                    r = procreg.reap_orphans()
                    if r["killed"]:
                        print(f"[{now:%H:%M}] reaped {r['killed']} orphan "
                              f"process(es) from {r['dead_owners']} dead "
                              f"owner(s)")
                        store.save_run("reaper",
                                       f"reaped {r['killed']} orphan node "
                                       f"process(es)", r)
                except Exception as exc:      # never kill the daemon
                    print(f"[{now:%H:%M}] reaper error: {exc}")
                next_reap = now + timedelta(hours=1)

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
            delivery = _deliver(job, out.strip() or f"exit {proc.returncode}")
            store.save_run("cron", f"[{job.get('name')}] exit {proc.returncode}",
                           {"output": out[:2000], "job": job["id"],
                            "delivery": delivery})
        elif jtype == "prompt":
            from .runtime import ConfigError, build_session
            try:
                session = build_session()
            except ConfigError as exc:
                store.save_run("cron", f"[{job.get('name')}] skipped: {exc}")
                return
            summary = session.ask(value)
            delivery = _deliver(job, summary)
            store.save_run("cron", f"[{job.get('name')}] {summary[:200]}",
                           {"summary": summary, "job": job["id"],
                            "delivery": delivery})
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
             "at": cron.schedule_display(j),
             "type": j.get("type"), "enabled": j.get("enabled", True),
             "last_run": j.get("last_run")}
            for j in cron.load_jobs()],
    })


# -- optional OS-native registration --------------------------------------

def install_os_schedule() -> int:
    """Register the OS task that keeps `birkin daemon` running.

    The daemon, not a one-shot, because ``run_daemon`` is the only thing that
    polls ``cron.due_jobs`` — it covers BOTH duties (Morpheus at
    ``morpheus_hour`` and the cron queue every 30s). This used to register
    ``-m birkin morpheus``, so every cron job a user scheduled, and everything
    ``/remind`` created, silently never fired: birkin said "scheduled" and
    nothing was.

    The daemon reads ``morpheus_hour``/``morpheus_minute`` from config itself,
    so the OS task carries no time — it only has to start the process and let
    it survive. Uses Task Scheduler on Windows and crontab elsewhere. Opt-in.
    The task / crontab entry name stays ``birkin-nightly`` so re-running this
    REPLACES an existing (including the old morpheus-only) installation
    instead of leaving both.
    """
    cfg = config.load_config()
    py = sys.executable

    if sys.platform.startswith("win"):
        roots = cfg.get("workspace_roots") or []
        working_dir = str(Path(roots[0]).expanduser() if roots else Path.cwd())
        cmd = f'cmd.exe /d /c "cd /d ""{working_dir}"" && ""{py}"" -m birkin daemon"'
        # ONLOGON, not DAILY: a 30s poll loop cannot live in a one-shot. /ST is
        # rejected in combination with ONLOGON, hence no start time here.
        args = ["schtasks", "/Create", "/SC", "ONLOGON", "/TN", "birkin-nightly",
                "/TR", cmd, "/F"]
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

    # POSIX: append a crontab line if not present. @reboot for the same reason
    # ONLOGON is used above — the daemon has to stay up to poll the queue.
    line = f"@reboot {py} -m birkin daemon  # birkin-nightly"
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
