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
import getpass
import json
import os
import plistlib
import shlex
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import config, cron, delivery, monitor, store
from .proc import (
    ShellCommand,
    run_shell_command,
    shell_env,
    windows_shell_argv,
)

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
    """Deliver a job output through its policy-gated channel.

    Returns a short status recorded with the run: ``sent`` /
    ``skipped-silent`` / ``none`` (no deliver target) / ``error: …``."""
    chat = str(job.get("deliver_chat_id") or "").strip()
    if not chat:
        return "none"
    if _is_silent(text):
        return "skipped-silent"
    cfg = config.load_config()
    channel = str(job.get("deliver_channel") or "telegram").strip().lower()
    message = f"[{job.get('name', 'cron')}] {text}"
    if channel in {"slack", "discord"}:
        from .gateway.channels.registry import resolve_delivery_target

        settings = ((cfg.get("channels") or {}).get(channel) or {})
        allowed = [
            str(value)
            for value in settings.get("allowed_channel_ids", [])
        ]
        if not allowed or chat not in allowed:
            return (
                f"error: channel_id not in "
                f"channels.{channel}.allowed_channel_ids"
            )
        adapter = resolve_delivery_target(channel, cfg)
        if adapter is None:
            return f"error: {channel} delivery is disabled or invalid"
        obligation = delivery.record(channel, chat, message)
        if obligation is None:
            return "error: could not record delivery obligation"
        try:
            sent = bool(adapter.send(chat, message))
        except Exception as exc:
            return f"error: {exc}"
        if not sent:
            return f"error: {channel} webhook delivery failed"
        delivery.clear(obligation)
        return "sent"
    if channel != "telegram":
        return f"error: unsupported delivery channel {channel!r}"
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
        _send_telegram(token, chat, message)
        return "sent"
    except Exception as exc:                    # network/HTTP — job still ran
        return f"error: {exc}"


def deliver(
    name: str,
    chat_id: str | None,
    text: str,
    *,
    channel: str = "telegram",
) -> str:
    """Public one-shot delivery to a Telegram chat, honoring the [SILENT]
    convention and the outbound allowlist — used by Morpheus for the
    morning digest (P0-3) in addition to cron jobs."""
    return _deliver(
        {
            "name": name,
            "deliver_channel": channel,
            "deliver_chat_id": chat_id or "",
        },
        text,
    )


def redeliver_send_only_channels() -> int:
    """Replay crash-surviving Slack and Discord delivery obligations."""
    from .gateway.channels.registry import resolve_delivery_target

    cfg = config.load_config()
    sent = 0
    for channel in ("slack", "discord"):
        settings = ((cfg.get("channels") or {}).get(channel) or {})
        allowed = frozenset(
            str(value) for value in settings.get("allowed_channel_ids", [])
        )
        adapter = resolve_delivery_target(channel, cfg)
        if adapter is None:
            continue

        def send(channel_id: str, text: str) -> bool:
            return channel_id in allowed and bool(adapter.send(channel_id, text))

        sent += delivery.redeliver(
            channel,
            send,
            prefix="[redelivery]\n",
        )
    return sent


def _send_checkin(chat_id: str, text: str, markup: str) -> str | None:
    """Send one check-in with its inline keyboard; return the message_id.

    Honors the same outbound allowlist as cron delivery, re-checked here at send
    time rather than only when the commitment was created.
    """
    cfg = config.load_config()
    tg = (cfg.get("channels") or {}).get("telegram") or {}
    allowed = [str(x) for x in (tg.get("allowed_chat_ids") or [])]
    if not allowed or chat_id not in allowed:
        return None
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or tg.get("token") or ""
    if not token:
        return None
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text[:3500],
                                   "reply_markup": markup}).encode()
    req = urllib.request.Request(_TG_SEND.format(token=token), data=body)
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    if not payload.get("ok"):
        return None
    return str((payload.get("result") or {}).get("message_id") or "")


def run_checkins(now: datetime | None = None, *, send=_send_checkin) -> int:
    """Deliver every due, eligible commitment check-in. Returns how many went.

    The claim happens before the network call, so a crash between the two loses
    one check-in rather than sending it twice — the same at-most-once trade
    ``cron.claim_if_due`` makes.
    """
    from . import companion
    from .gateway.channels.telegram import TelegramChannel
    sent = 0
    for record in companion.due_checkins(now):
        ok, _key = companion.claim_checkin(record["id"], now=now)
        if not ok:
            continue
        chat_id = str(record["context_id"]).partition(":")[2]
        text = (companion.checkin_text(record) + "\n\n"
                + companion.why_message(record))
        try:
            message_id = send(chat_id, text,
                              TelegramChannel.companion_markup(record["id"]))
        except Exception as exc:
            companion.append_event(kind="checkin_send_failed",
                                   context_id=record["context_id"],
                                   commitment_id=record["id"],
                                   summary=f"send failed: {exc}")
            continue
        if message_id is None:
            companion.append_event(kind="checkin_send_failed",
                                   context_id=record["context_id"],
                                   commitment_id=record["id"],
                                   summary="send refused: chat not allowed or "
                                           "no token")
            continue
        companion.record_delivery(record["id"], message_id)
        sent += 1
    return sent


def _morpheus_hour(cfg: dict[str, Any]) -> int:
    """Read the configured Morpheus hour, honoring the legacy ``nightly_hour``
    key so existing config.json files keep working unchanged."""
    return int(cfg.get("morpheus_hour", cfg.get("nightly_hour", 7)))


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


def already_running() -> bool:
    """Is another daemon alive right now?

    Cron jobs are safe against a second daemon — ``cron.claim_if_due`` stamps
    them atomically — but the Morpheus trigger below is a plain time comparison
    per process, so two daemons would run the nightly routine TWICE: real
    duplicated model spend. Nothing prevented that before, and the collision is
    one step away now that a Startup entry fires at logon while a hand-started
    daemon may already be up.

    The heartbeat already exists; this just reads it. A crashed daemon leaves a
    stale heartbeat, which ``is_status_stale`` treats as stopped, so this
    cannot wedge shut.

    (Counting OS processes is NOT a substitute: on Windows a venv's
    ``Scripts/python.exe`` is a launcher stub that runs the real interpreter as
    a child, so one daemon shows up as two python.exe entries with identical
    command lines.)
    """
    status = store.read_status()
    return bool(status.get("daemon")) and not store.is_status_stale(status)


def run_daemon() -> int:
    if already_running():
        print("birkin daemon: 이미 실행 중입니다 (heartbeat 확인). "
              "중복 실행은 Morpheus를 두 번 돌리므로 종료합니다.")
        return 0
    cfg = config.load_config()
    next_morpheus = _next_morpheus(cfg, datetime.now())
    next_reap = datetime.now() + timedelta(hours=1)
    print(f"birkin daemon started. Next Morpheus run at "
          f"{next_morpheus:%Y-%m-%d %H:%M}. Ctrl-C to stop.")
    _write_status(cfg, next_morpheus, running=True)
    redelivered = redeliver_send_only_channels()
    if redelivered:
        print(f"redelivered {redelivered} pending webhook message(s)")

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
                claimed = cron.claim_if_due(job["id"], now)
                if claimed is None:
                    continue
                print(
                    f"[{now:%H:%M}] running cron job "
                    f"'{claimed.get('name')}'…"
                )
                run_job(claimed)

            try:
                delivered = run_checkins()
                if delivered:
                    print(f"[{now:%H:%M}] sent {delivered} commitment "
                          f"check-in(s)")
            except Exception as exc:      # never kill the daemon
                print(f"[{now:%H:%M}] check-in error: {exc}")

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


def run_job(job: dict[str, Any]) -> None:
    jtype = job.get("type", "prompt")
    value = job.get("value", "")
    try:
        if jtype == "monitor":
            result = monitor.check(job)
            if not result.changed:
                status = (f"monitor error: {result.error}"
                          if result.error else "unchanged")
                silent = f"[SILENT] {status}"
                delivery = _deliver(job, silent)
                store.save_run(
                    "cron", f"[{job.get('name')}] {silent}",
                    {"job": job["id"], "error": result.error,
                     "delivery": delivery},
                    usage={"tokens": 0},
                )
                return
            context = ["[Monitor change context]"]
            if result.diff_context:
                context.extend(["", result.diff_context])
            if result.content_tail:
                context.extend(["", "Content tail:", result.content_tail])
            value = f"{value}\n\n" + "\n".join(context)
            jtype = "prompt"

        if jtype == "shell":
            proc = run_shell_command(
                ShellCommand(
                    command=value,
                    cwd=None,
                    timeout=600,
                    environment=shell_env(),
                    hide_window=True,
                )
            )
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
            # record_turn=False: the "cron" record below IS this event's
            # record. Letting ask() also file a "chat" run wrote two records
            # per firing with the same timestamp — and double-counted the
            # tokens in the ledger and the daily budget. Morpheus already
            # passes the same flag for the same reason.
            summary = session.ask(value, record_turn=False)
            delivery = _deliver(job, summary)
            store.save_run("cron", f"[{job.get('name')}] {summary[:200]}",
                           {"summary": summary, "job": job["id"],
                            "delivery": delivery})
        elif jtype == "briefing":
            from .daily_briefing import generate

            options = json.loads(str(value) or "{}")
            scheduled = datetime.fromisoformat(str(job.get("next_run")))
            if options.get("missed_policy") == "skip" and datetime.now() - scheduled > timedelta(minutes=5):
                store.save_run("briefing", f"[{job.get('name')}] skipped missed run", {"job": job["id"], "policy": "skip"})
                return
            report = generate(job)
            if report.get("created") is True:
                store.save_run("briefing", f"[{job.get('name')}] briefing ready", {"job": job["id"], "briefing_id": report["id"], "delivery": "in_app_only"}, usage={"tokens": 0})
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

_MACOS_LAUNCH_AGENT_LABEL = "dev.birkin.daemon"


def _macos_gui_domain() -> str:
    return f"gui/{os.getuid()}"


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
    it survive. Uses Task Scheduler on Windows, launchd on macOS, and crontab
    on Linux. Opt-in.
    The task / crontab entry name stays ``birkin-nightly`` so re-running this
    REPLACES an existing (including the old morpheus-only) installation
    instead of leaving both.
    """
    cfg = config.load_config()
    py = sys.executable
    roots = cfg.get("workspace_roots") or []
    working_dir = str(Path(roots[0]).expanduser() if roots else Path.cwd())

    if sys.platform.startswith("win"):
        system_root = os.environ.get("SystemRoot") or r"C:\Windows"
        interpreter = windows_shell_argv("", system_root)[0]
        cmd = (
            f'"{interpreter}" /d /s /c '
            f'"cd /d ""{working_dir}"" && ""{py}"" -m birkin daemon"'
        )
        # ONLOGON, not DAILY: a 30s poll loop cannot live in a one-shot. /ST is
        # rejected in combination with ONLOGON, hence no start time here.
        #
        # /RU + /IT are load-bearing, not decoration. An ONLOGON task with no
        # /RU triggers on ANY user's logon, which is an administrator-only
        # registration — a plain user gets "Access is denied" with nothing
        # naming the cause. Scoping it to this account (and /IT, run only while
        # that account is actually logged on) keeps it installable without
        # elevation and without a stored password, which is also how the old
        # DAILY task ended up as "Run As User: <you>, Logon Mode: Interactive".
        user = os.environ.get("USERNAME") or getpass.getuser()
        args = ["schtasks", "/Create", "/SC", "ONLOGON", "/TN", "birkin-nightly",
                "/TR", cmd, "/RU", user, "/IT", "/F"]
        try:
            # schtasks prints in the Windows OEM codepage (e.g. cp949 on Korean
            # Windows); decode with "oem" so the message is readable.
            proc = subprocess.run(args, capture_output=True, text=True,
                                  encoding="oem", errors="replace")
        except FileNotFoundError:
            print("schtasks not available on this system.")
            return 1
        if proc.returncode == 0:
            print((proc.stdout or proc.stderr).strip())
            return 0
        # Denied is the NORMAL outcome for a non-administrator. Measured on
        # Windows 11: DAILY succeeds for a plain user, ONLOGON is refused with
        # or without /RU — the logon trigger is the privileged part, not the
        # account scoping. Fall back rather than making the user run an
        # elevated shell for a personal background task.
        print((proc.stdout or proc.stderr).strip())
        return _install_windows_startup(py, working_dir)

    if sys.platform == "darwin":
        return _install_macos_launch_agent(py, working_dir)
    return _install_posix_crontab(py)


def _install_macos_launch_agent(py: str, working_dir: str) -> int:
    agent = (
        Path.home()
        / "Library"
        / "LaunchAgents"
        / f"{_MACOS_LAUNCH_AGENT_LABEL}.plist"
    )
    agent.parent.mkdir(parents=True, exist_ok=True)
    log_dir = Path.home() / "Library" / "Logs" / "birkin"
    log_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": _MACOS_LAUNCH_AGENT_LABEL,
        "ProgramArguments": [py, "-m", "birkin", "daemon"],
        "WorkingDirectory": working_dir,
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log_dir / "daemon.stdout.log"),
        "StandardErrorPath": str(log_dir / "daemon.stderr.log"),
    }
    tmp = agent.with_suffix(".plist.tmp")
    tmp.write_bytes(plistlib.dumps(payload))
    os.replace(tmp, agent)

    domain = _macos_gui_domain()
    subprocess.run(
        ["launchctl", "bootout", f"{domain}/{_MACOS_LAUNCH_AGENT_LABEL}"],
        capture_output=True,
        text=True,
        errors="replace",
    )
    proc = subprocess.run(
        ["launchctl", "bootstrap", domain, str(agent)],
        capture_output=True,
        text=True,
        errors="replace",
    )
    if proc.returncode == 0:
        print(f"Installed macOS LaunchAgent: {agent}")
    else:
        print(proc.stderr)
    return proc.returncode


def _install_windows_startup(py: str, working_dir: str) -> int:
    """No-elevation fallback: a .cmd in this account's Startup folder.

    The daemon has to be resident to poll the cron queue at all, and Startup is
    the mechanism Windows gives an unprivileged user for "run this at my logon".
    One plain-text file the user can read and delete.
    """
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    startup = (Path(appdata) / "Microsoft" / "Windows" / "Start Menu"
               / "Programs" / "Startup")
    try:
        startup.mkdir(parents=True, exist_ok=True)
        path = startup / "birkin-daemon.cmd"
        path.write_text(f'@echo off\r\ncd /d "{working_dir}"\r\n'
                        f'start "" /min "{py}" -m birkin daemon\r\n',
                        encoding="utf-8")
    except OSError as exc:
        print(f"시작 프로그램 등록도 실패했습니다: {exc}")
        return 1
    print(f"\n관리자 권한이 없어 작업 스케줄러 대신 시작 프로그램에 등록했습니다:\n"
          f"  {path}\n  (지우려면 이 파일만 삭제하세요. 다음 로그인부터 적용됩니다.)")
    # The old birkin-nightly task ran `birkin morpheus` on its own. Leaving it
    # alongside the daemon means Morpheus runs twice every night — real
    # duplicated model spend — so retire it now that the daemon covers it.
    try:
        gone = subprocess.run(["schtasks", "/Delete", "/TN", "birkin-nightly",
                               "/F"], capture_output=True, text=True,
                              encoding="oem", errors="replace")
        if gone.returncode == 0:
            print("  기존 birkin-nightly 작업은 제거했습니다 "
                  "(데몬이 Morpheus까지 맡으므로 중복 실행 방지).")
    except (FileNotFoundError, OSError):
        pass
    return 0


def _install_posix_crontab(py: str) -> int:
    # Append a crontab line if not present. @reboot for the same reason the
    # daemon is used above — it has to stay up to poll the queue.
    line = (
        f"@reboot {shlex.quote(py)} -m birkin daemon  # birkin-nightly"
    )
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
