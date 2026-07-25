"""`birkin moirai …` — run, inspect and resume workflows.

Entry is always explicit and always here: no tool lets a model start a
workflow, because that is the one spawn path with no natural ceiling.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .. import config, ui
from . import bindings as B
from . import journal
from .engine import MoiraiError, load_script, run_script


def scripts_dir() -> Path:
    d = config.birkin_home() / "moirai" / "scripts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_script_path(name: str) -> Path:
    """Accept a path, or a bare name resolved against the scripts directory."""
    raw = (name or "").strip()
    if not raw:
        raise MoiraiError("워크플로우를 지정하세요 (경로 또는 이름)")
    direct = Path(raw).expanduser()
    if direct.is_file():
        return direct
    bundled = Path(__file__).resolve().parent / "patterns"
    for candidate in (scripts_dir() / raw, scripts_dir() / f"{raw}.py",
                      bundled / raw, bundled / f"{raw}.py",
                      bundled / f"{raw.replace('-', '_')}.py"):
        if candidate.is_file():
            return candidate
    raise MoiraiError(f"워크플로우를 찾을 수 없습니다: {raw}")


def cmd_run(args: Any) -> int:
    cfg = config.load_config()
    try:
        script = load_script(resolve_script_path(getattr(args, "script", "")))
    except MoiraiError as exc:
        print(f"{ui.RED}{exc}{ui.RESET}")
        return 1

    try:
        cli_binds = B.parse_cli_binds(getattr(args, "bind", None))
        resolved = B.resolve(
            script.roles, cli=cli_binds,
            last=journal.last_bindings(script.name), cfg=cfg)
        B.check_roles_used(script.roles, script.roles_used())
        B.validate(resolved, cfg)
    except B.BindingError as exc:
        print(f"{ui.RED}{exc}{ui.RESET}")
        return 1

    run_args = _parse_args_json(getattr(args, "args", None))
    if run_args is None:
        print(f"{ui.RED}--args는 JSON 객체여야 합니다{ui.RESET}")
        return 1

    print(f"{ui.BOLD}{script.name}{ui.RESET}"
          + (f" — {script.description}" if script.description else ""))
    for role, b in resolved.items():
        print(f"  {role:<12} {b.spec:<28} {ui.DIM}[{b.source_label}]{ui.RESET}")

    try:
        out = run_script(script, cfg=cfg, bindings_map=resolved,
                         args=run_args, on_event=ui.make_event_printer())
    except MoiraiError as exc:
        print(f"{ui.RED}{exc}{ui.RESET}")
        return 1

    _print_outcome(out)
    return 0 if out["status"] == "completed" else 1


def cmd_resume(args: Any) -> int:
    run_id = (getattr(args, "run_id", "") or "").strip()
    prior = journal.get_run(run_id)
    if not prior:
        print(f"{ui.RED}그런 실행이 없습니다: {run_id}{ui.RESET}")
        return 1
    cfg = config.load_config()
    try:
        script = load_script(prior["script_path"])
    except MoiraiError as exc:
        print(f"{ui.RED}{exc}{ui.RESET}")
        return 1

    if script.sha256 != prior["script_sha256"]:
        print(f"{ui.YELLOW}스크립트가 변경됐습니다 — 바뀐 지점부터 다시 "
              f"실행합니다.{ui.RESET}")

    stored = json.loads(prior.get("bindings_json") or "{}")
    roles = {r: {"default": s} for r, s in stored.items()} or script.roles
    resolved = B.resolve(roles, cli=B.parse_cli_binds(
        getattr(args, "bind", None)), cfg=cfg)
    B.validate(resolved, cfg)

    out = run_script(script, cfg=cfg, bindings_map=resolved,
                     args=json.loads(prior.get("args_json") or "{}"),
                     resume_from=run_id, on_event=ui.make_event_printer())
    _print_outcome(out)
    return 0 if out["status"] == "completed" else 1


def cmd_list(args: Any) -> int:
    bundled = Path(__file__).resolve().parent / "patterns"
    files = sorted(scripts_dir().glob("*.py")) + [
        f for f in sorted(bundled.glob("*.py")) if f.name != "__init__.py"]
    if files:
        print(f"{ui.BOLD}워크플로우{ui.RESET}  ({scripts_dir()})")
        for f in files:
            try:
                script = load_script(f)
                print(f"  {script.name:<20} {script.description[:52]}")
            except MoiraiError:
                print(f"  {f.stem:<20} {ui.RED}(로드 실패){ui.RESET}")
    else:
        print(f"{ui.DIM}워크플로우가 없습니다 — {scripts_dir()}에 "
              f".py 파일을 두세요.{ui.RESET}")

    runs = journal.list_runs(limit=int(getattr(args, "limit", 10) or 10))
    if runs:
        print(f"\n{ui.BOLD}최근 실행{ui.RESET}")
        for r in runs:
            mark = {"completed": "✓", "error": "✗", "aborted": "⊘"}.get(
                r["status"], "·")
            print(f"  {mark} {r['run_id']}  {r['name']:<18} "
                  f"{ui.DIM}{r['started']}{ui.RESET}")
    return 0


def cmd_status(args: Any) -> int:
    run_id = (getattr(args, "run_id", "") or "").strip()
    run = journal.get_run(run_id)
    if not run:
        print(f"{ui.RED}그런 실행이 없습니다: {run_id}{ui.RESET}")
        return 1
    print(f"{ui.BOLD}{run['name']}{ui.RESET}  {run['run_id']}  "
          f"[{run['status']}]")
    print(f"  script  {run['script_path']}")
    print(f"  bindings {run['bindings_json']}")
    print(f"  started {run['started']}  finished {run['finished'] or '—'}")

    calls = journal.run_calls(run_id)
    if calls:
        print(f"\n  {'seq':>3}  {'phase':<10} {'label':<16} "
              f"{'model':<24} {'status':<7} {'sec':>6}")
        for c in calls:
            secs = _elapsed(c)
            print(f"  {c['seq']:>3}  {(c['phase'] or ''):<10} "
                  f"{(c['label'] or ''):<16} "
                  f"{(c['provider'] + ':' + (c['model'] or '')):<24} "
                  f"{c['status']:<7} {secs:>6}")
            if c["status"] == "error" and c["error"]:
                print(f"       {ui.RED}{c['error'][:160]}{ui.RESET}")
    return 0


def _elapsed(call: dict) -> str:
    from datetime import datetime
    try:
        dt = (datetime.fromisoformat(call["finished"])
              - datetime.fromisoformat(call["started"])).total_seconds()
        return f"{dt:.1f}"
    except Exception:
        return "—"


def _parse_args_json(raw: Optional[str]) -> Optional[dict]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _print_outcome(out: dict) -> None:
    mark = {"completed": ui.CYAN + "✓", "error": ui.RED + "✗",
            "aborted": ui.YELLOW + "⊘"}.get(out["status"], "·")
    cached = (f" · 캐시 {out['cache_hits']}" if out.get("cache_hits") else "")
    print(f"\n{mark} {out['status']}{ui.RESET} — 에이전트 {out['agents']}"
          f"{cached} · {out['seconds']}s · ~{out['tokens']} 토큰")
    print(f"{ui.DIM}  {out['run_id']}  (birkin moirai status <id>){ui.RESET}")
    if out.get("result") is not None:
        rendered = json.dumps(out["result"], ensure_ascii=False, indent=1,
                              default=str)
        print(rendered if len(rendered) < 1200 else rendered[:1200] + " …")
