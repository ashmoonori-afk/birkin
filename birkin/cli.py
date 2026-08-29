"""birkin command-line entry point.

Subcommands:
  (none) / chat   start interactive chat
  skills [name]   list skills, or print one in full
  web             launch the local WebUI
  setup           configure provider / model / API key
  nightly         run the 7 AM self-improvement routine now
  daemon          run the scheduler that triggers nightly + cron jobs
  review          review and approve/reject pending proposed actions
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__


def _cmd_chat(args: argparse.Namespace) -> int:
    from . import config
    positional = getattr(args, "positional_message", None)
    if positional and not getattr(args, "dry_run", False):
        print("positional chat message requires --dry-run", file=sys.stderr)
        return 2
    if getattr(args, "dry_run", False):
        return _dry_run(args)
    if not config.config_path().exists():  # first run -> onboard
        from .onboarding import run as onboard
        onboard()
        print()
    from .repl import run
    return run()


def _dry_run(args: argparse.Namespace) -> int:
    """Build and print the prompt packet for a message — no model call, no key."""
    from .runtime import build_dry_run_packet
    from .ui import BOLD, CYAN, DIM, RESET
    positional = getattr(args, "positional_message", None)
    if args.message and positional:
        print(
            "choose either positional message or --message, not both",
            file=sys.stderr,
        )
        return 2
    msg = args.message or positional
    if not msg:
        try:
            msg = input("Message to inspect: ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
    if not msg:
        return 0
    packet = build_dry_run_packet(msg)
    print(f"{BOLD}=== dry run (no model called) ==={RESET}")
    print(f"provider: {CYAN}{packet['provider']}{RESET}  model: {packet['model']}")
    print(f"\n{BOLD}--- system prompt ---{RESET}\n{packet['system']}")
    if packet["tools"]:
        print(f"\n{BOLD}--- tools ---{RESET}\n{', '.join(packet['tools'])}")
    if packet["routed_skills"]:
        print(f"\n{BOLD}--- routed skills ---{RESET}\n{', '.join(packet['routed_skills'])}")
    print(f"\n{BOLD}--- user ---{RESET}\n{packet['user']}")
    u = packet["usage"]
    print(f"\n{DIM}estimate: {u['chars']} chars, ~{u['estTokens']} tokens. "
          f"No request was sent.{RESET}")
    return 0


def _cmd_worker_hook_qa(args: argparse.Namespace) -> int:
    """Deprecated compatibility alias for the importable QA driver."""
    from . import worker_hook_qa

    print(
        "deprecated: use `python -m birkin.worker_hook_qa --decision ...`",
        file=sys.stderr,
    )
    return worker_hook_qa.run(args.decision)


def _cmd_lineage(args: argparse.Namespace) -> int:
    """Inspect and recover trusted compaction lineage."""
    from . import lineage

    try:
        if args.lineage_action == "list":
            print(json.dumps(lineage.list_snapshots(), ensure_ascii=False))
        elif args.lineage_action == "recover":
            print(json.dumps(lineage.recover(args.snapshot_id), ensure_ascii=False))
        elif args.lineage_action == "prune":
            print(json.dumps(lineage.prune(keep=args.keep)))
        elif args.lineage_action == "export":
            path = lineage.export_snapshot(
                args.snapshot_id,
                Path(args.destination),
            )
            print(path)
        else:
            raise ValueError("unknown lineage action")
    except (OSError, ValueError) as exc:
        print(f"lineage: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    """Blind A/B: run one prompt through two models, reveal which is which after."""
    from . import compare, config
    from .ui import BOLD, CYAN, DIM, RESET
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        print("Give a prompt:  birkin compare \"<prompt>\"  [--a opus --b sonnet]")
        return 1
    cfg = config.load_config()
    a, b = compare.default_pair(cfg, args.a, args.b)
    print(f"{DIM}comparing (blind): two models on the same prompt…{RESET}\n")
    res = compare.run(cfg, prompt, a, b)
    print(f"{BOLD}=== A ==={RESET}\n{res['A']['text']}\n")
    print(f"{BOLD}=== B ==={RESET}\n{res['B']['text']}")
    if sys.stdin.isatty():
        try:
            input(f"\n{DIM}Press Enter to reveal which model is which…{RESET} ")
        except (EOFError, KeyboardInterrupt):
            print()
    print(f"\n{CYAN}A = {res['A']['model']}    B = {res['B']['model']}{RESET}")
    return 0


def _cmd_plugins(args: argparse.Namespace) -> int:
    """Inspect, install, and resolve exact plugin bundle pins."""
    from .config import load_config
    from .plugin_install import (
        PluginInstallError,
        PluginInstaller,
        Scope,
        plugin_trust_policy,
    )
    from .plugin_manifest import ManifestError
    from .plugin_runtime import registry_roots
    from .plugin_signature import SignatureError

    keys: dict[str, bytes] = {}
    try:
        for item in args.key or []:
            key_id, separator, encoded = item.partition("=")
            if not separator or not key_id:
                raise ValueError("trusted keys use KEY_ID=HEX")
            keys[key_id] = bytes.fromhex(encoded)
        configured_keys, allow_unsigned = plugin_trust_policy(load_config())
        project_root, team_root = registry_roots()
        installer = PluginInstaller(
            project_root,
            team_root,
            {**configured_keys, **keys},
            allow_unsigned=allow_unsigned,
        )
        if args.action == "resolve":
            found = installer.resolve(args.name, args.version)
            record = {"name": found.name, "version": found.version,
                      "scope": found.scope.value, "path": str(found.path),
                      "digest": found.digest}
            print(json.dumps(record, sort_keys=True) if args.json else
                  f"{found.name}@{found.version} [{found.scope.value}] {found.path}")
            return 0
        source = Path(args.source).expanduser().resolve()
        inspection = installer.inspect(source)
        record = inspection.machine_record()
        if args.json:
            print(json.dumps(record, sort_keys=True))
        else:
            permissions = record["permissions"]
            assert isinstance(permissions, dict)
            print(f"Bundle: {inspection.manifest.name}@{inspection.manifest.version}")
            print(f"Signature: {inspection.signature}")
            print("Required permissions:")
            print(f"  network: {permissions['network']}")
            for field in ("network_allowlist", "env_allowlist", "write_paths"):
                values = permissions[field]
                assert isinstance(values, list)
                print(f"  {field}: {', '.join(values) if values else '(none)'}")
            print("Confirmation required: " +
                  ("yes" if inspection.manifest.requires_confirmation else "no"))
        if args.action == "inspect":
            return 0
        confirmed = bool(args.yes)
        if inspection.manifest.requires_confirmation and not confirmed:
            if args.json:
                print(json.dumps({"error": "confirmation required"}, sort_keys=True))
                return 1
            try:
                confirmed = input("Install with these permissions? [y/N] ").strip().lower() in ("y", "yes")
            except (EOFError, KeyboardInterrupt):
                confirmed = False
            if not confirmed:
                print("Installation refused; no files were changed.")
                return 1
        installed = installer.install(
            source, Scope(args.scope), args.version,
            confirmed=confirmed, upgrade=args.upgrade,
        )
        result = {"name": installed.name, "version": installed.version,
                  "scope": installed.scope.value, "path": str(installed.path),
                  "digest": installed.digest}
        print(json.dumps(result, sort_keys=True) if args.json else
              f"Installed {installed.name}@{installed.version} [{installed.scope.value}]")
        return 0
    except (ManifestError, SignatureError, PluginInstallError, OSError, ValueError) as exc:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc)}, sort_keys=True))
        else:
            print(f"Plugin error: {exc}")
        return 1


def _cmd_plugin_effects(args: argparse.Namespace) -> int:
    from . import tool_effect_cli
    effect_args = list(args.effect_args)
    if args.effect_json:
        effect_args.append("--json")
    return tool_effect_cli.run(effect_args)


def _cmd_skills(args: argparse.Namespace) -> int:
    from . import config
    from .skills import build_manager
    if args.name in ("install", "uninstall", "audit", "scan"):
        return {"install": _skills_install, "uninstall": _skills_uninstall,
                "audit": _skills_audit, "scan": _skills_scan}[args.name](args)
    if args.name == "sync":
        return _skills_sync(args)
    if args.name == "validate":
        return _skills_validate(args)
    mgr = build_manager(config.load_config())
    if args.name:
        sk = mgr.get(args.name)
        if not sk:
            print(f"No skill named {args.name!r}")
            return 1
        print(sk.full())
        return 0
    if not mgr.skills:
        print("No skills installed.")
        return 0
    print(mgr.index())
    return 0


def _skills_sync(args: argparse.Namespace) -> int:
    """`birkin skills sync [--from DIR] [--limit N] [--force]` — mirror upstream
    (hermes) skills into ~/.birkin/skills/mirrors with attribution."""
    from pathlib import Path

    from .skills import sync
    sources = [Path(args.source)] if args.source else sync.autodetect_sources()
    if not sources:
        print("No source found. Pass --from <skills-dir> (e.g. a hermes skills "
              "directory).")
        return 1
    total = 0
    for src in sources:
        try:
            synced = sync.sync_skills(src, limit=args.limit, force=args.force)
        except NotADirectoryError:
            print(f"Not a directory: {src}")
            continue
        print(f"From {src}: mirrored {len(synced)} skill(s).")
        for name in synced[:20]:
            print(f"  + {name}")
        total += len(synced)
    print(f"\nTotal mirrored: {total}. They appear in `birkin skills` after reload.")
    return 0


def _skills_validate(args: argparse.Namespace) -> int:
    """`birkin skills validate [--verbose]` — lint frontmatter + py_compile
    bundled scripts across bundled / user / extra skill directories. Exits
    non-zero on any error."""
    from .skills import validate as skv
    summary = skv.validate_all()
    print(skv.format_summary(summary, verbose=getattr(args, "verbose", False)))
    return 0 if summary.ok else 1


def _skills_install(args) -> int:
    """`birkin skills install <source> [--force]` — quarantine, scan, install.

    ``<source>`` is ``owner/repo[/path]``, a local directory, or an https URL
    to a SKILL.md. Every one lands in quarantine and is scanned there first;
    only the way the bytes arrive differs."""
    from .skills import hub

    def confirm(report: str) -> bool:
        print(report)
        print("\nThis skill comes from a third party. Its SKILL.md becomes "
              "instructions your agent follows, and its scripts run on this "
              "machine.")
        try:
            return input("Install it? [y/N] ").strip().lower() in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

    identifier = (getattr(args, "target", "") or "").strip()
    if not identifier:
        print("Which skill? `birkin skills install <owner/repo[/path] | "
              "./local/dir | https://…/SKILL.md>`")
        return 1
    ok, report = hub.install(identifier, force=args.force, confirm=confirm)
    print(report)
    return 0 if ok else 1


def _skills_uninstall(args) -> int:
    """`birkin skills uninstall <name>` — remove an installed hub skill."""
    from .skills import hub
    name = (args.target or "").strip()
    if not name:
        print("Which skill? `birkin skills uninstall <name>`")
        return 1
    try:
        removed = hub.uninstall(name)
    except hub.HubError as exc:
        print(f"Refused: {exc}")
        return 1
    print(f"Removed {name}." if removed else f"Not installed: {name}")
    return 0 if removed else 1


def _skills_audit(args) -> int:
    """`birkin skills audit` — installed hub skills and the install log."""
    from .skills import hub
    lock = hub.load_lock()
    if lock:
        print("Installed from the hub:")
        for name, entry in sorted(lock.items()):
            print(f"  {name:<24} {entry.get('identifier', '?'):<36} "
                  f"{entry.get('verdict', '?')}/{entry.get('trust', '?')}")
    else:
        print("No hub-installed skills.")
    lines = hub.read_audit()
    if lines:
        print("\nRecent activity:")
        for line in lines:
            print(f"  {line}")
    return 0


def _skills_scan(args) -> int:
    """`birkin skills scan <dir>` — run the security scanner over a bundle."""
    from pathlib import Path as _Path

    from .skills import guard
    target = _Path(args.target or ".").expanduser()
    result = guard.scan_skill(target, source=args.source or "community")
    print(guard.format_report(result, target.name))
    return 0 if result.verdict != "dangerous" else 1


def _cmd_web(args: argparse.Namespace) -> int:
    from .web import run
    return run(port=args.port, open_browser=not args.no_browser)


def _cmd_native_bridge(args: argparse.Namespace) -> int:
    from .native.serve import NativeServeOptions, serve_bridge

    return serve_bridge(NativeServeOptions.resolve(
        transport=args.transport,
        session_id=args.session_id,
        root=args.root,
    ))


def _cmd_native_provider_probe(args: argparse.Namespace) -> int:
    from .native.provider_probe import emit_probe

    return emit_probe(provider=args.provider, model=args.model, output=args.output)


def _cmd_setup(args: argparse.Namespace) -> int:
    from .onboarding import run
    return run()


def _cmd_model(args: argparse.Namespace) -> int:
    """Pick the model from the CLI, hermes-style (`birkin model`)."""
    from . import config
    cfg = config.load_config()
    provider = cfg.get("provider", "anthropic")

    if args.name:  # non-interactive: set directly
        cfg["model"] = args.name
        config.save_config(cfg)
        print(f"Model set to {args.name}")
        return 0

    from . import models as models_mod
    print(f"Current model: {cfg.get('model')}  (provider: {provider})")
    print("(discovering API + local models…)")
    if models_mod.pick_interactive(cfg) is None:
        return 0
    config.save_config(cfg)
    print(f"Model set to {cfg['model']} (provider: {cfg.get('provider')})")
    return 0


def _cmd_morpheus(args: argparse.Namespace) -> int:
    from .morpheus import run_once
    return run_once(dry_run=args.dry_run)


def _cmd_update(args: argparse.Namespace) -> int:
    """Pull new repo code (main code + bundled skills); ~/.birkin user state is
    untouched. Restart the gateway/REPL afterwards to load the new code."""
    from .updater import update
    result = update()
    print(result["message"])
    if result.get("updated"):
        print("Restart the gateway (/hard_restart) or relaunch birkin to apply.")
    return 0 if result.get("ok") else 1


def _cmd_daemon(args: argparse.Namespace) -> int:
    from .scheduler import install_os_schedule, run_daemon
    if args.install:
        return install_os_schedule()
    return run_daemon()


def _cmd_review(args: argparse.Namespace) -> int:
    from .approvals import review_cli
    return review_cli()


def _cmd_gateway(args: argparse.Namespace) -> int:
    from .gateway import run
    return run()


def _cmd_harness(args: argparse.Namespace) -> int:
    """Read/undo/export the self-improvement ledger (harness)."""
    from pathlib import Path

    from . import harness
    scope = "global" if getattr(args, "global_scope", False) else args.scope
    session_id = getattr(args, "session_id", None)
    target = args.target[0] if args.target else ""

    if args.action == "show":
        block = harness.render_block(harness.load(scope, session_id=session_id))
        print(block or f"The {scope} harness is empty — nothing recorded yet. "
                       "Run `birkin morpheus` to propose the first refinements.")
        return 0

    if args.action == "history":
        events = harness.history(scope, limit=args.limit, session_id=session_id)
        if not events:
            print(f"No refinements recorded yet in the {scope} harness.")
            return 0
        for event in events:
            changes = ", ".join(event.get("changes") or []) or "(nothing applied)"
            print(f"{event.get('id')}  {event.get('created_at')}  {changes}")
        return 0

    if args.action == "rollback":
        if not target:
            print("rollback needs a refinement id — see `birkin harness history`.")
            return 1
        try:
            event = harness.rollback(target, scope, session_id=session_id)
        except KeyError as exc:
            print(f"error: {exc.args[0]}")
            return 1
        restored = ", ".join(event.get("changes") or []) or "(nothing to undo)"
        print(f"rolled back {target}: {restored} (recorded as {event['id']})")
        return 0

    if args.action == "export":
        if not target:
            print("export needs a path: `birkin harness export <path>`")
            return 1
        path = Path(target).expanduser()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            state = harness.load(scope, session_id=session_id)
            path.write_text(
                json.dumps(state, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"could not write {target}: {exc}")
            return 1
        print(f"wrote the {scope} harness state to {target}")
        return 0

    print("`birkin harness refine` has no proposal source of its own. Morpheus "
          "(`birkin morpheus`) and the in-session review pass produce harness "
          "proposals; non-auto-approved ones wait in `birkin review`. "
          f"Nothing in the {scope} harness was changed.")
    return 0


def _cmd_working_memory(args: argparse.Namespace) -> int:
    """Inspect or update the canonical current-task state for one session."""
    from . import goals, harness

    try:
        session_id = harness.validate_working_session_id(args.session)

        def snapshot_locked() -> dict[str, object]:
            working = harness.working_state(session_id)
            goal = goals.get_active(session_id=session_id)
            return {
                "schema": 1,
                "session_id": session_id,
                "revision": working["revision"],
                "goal": goal.objective if goal is not None else "",
                **{
                    field: list(working[field])
                    for field in harness.WORKING_FIELDS
                },
                "updated_at": (
                    working["updated_at"]
                    or (goal.updated_at if goal is not None else "")
                ),
            }

        def snapshot() -> dict[str, object]:
            with harness.working_transaction(session_id):
                return snapshot_locked()

        if args.working_memory_action == "show":
            if args.json:
                state = snapshot()
                print(json.dumps(state, ensure_ascii=False))
            else:
                with harness.working_transaction(session_id):
                    state = snapshot_locked()
                    goal = str(state["goal"])
                    block = harness.render_working(session_id)
                rendered = "\n\n".join(
                    part for part in (
                        f"Goal: {goal}" if goal else "",
                        block,
                    )
                    if part
                )
                print(rendered or "Working memory is empty.")
            return 0
        if args.working_memory_action == "clear":
            goal_removed = False

            def pause_goal() -> None:
                nonlocal goal_removed
                goal_removed = goals.pause(session_id=session_id) is not None

            removed = harness.clear_working(
                session_id,
                commit=pause_goal,
            )
            print(
                f"Cleared working memory for {session_id}."
                if removed or goal_removed
                else f"Working memory for {session_id} was already empty."
            )
            return 0

        updates = {
            "corrections": args.corrections,
            "constraints": args.constraints,
            "decisions": args.decisions,
            "incomplete": args.incomplete,
            "evidence": args.evidence,
            "next_actions": args.next_actions,
        }
        if args.goal is None and not any(
            updates.values()
        ):
            print("error: update needs at least one state value", file=sys.stderr)
            return 2
        if args.goal is not None and not str(args.goal).strip():
            raise ValueError("goal objective must not be empty")
        def commit() -> None:
            _ = goals.set_goal(args.goal, session_id=session_id)

        state = harness.update_working(
            session_id,
            **updates,
            commit=commit if args.goal is not None else None,
        )
        print(
            f"Updated working memory for {session_id} "
            f"(revision {state['revision']})."
        )
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _cmd_voice(args: argparse.Namespace) -> int:
    from .voice import onboarding
    from .voice.daemon import (
        start_daemon,
        status_daemon,
        stop_daemon,
    )
    from .voice.daemon_worker import run_worker

    if args.daemon_worker:
        return run_worker(args)
    if args.voice_action in {"setup", "onboard"}:
        return onboarding.run()
    if args.voice_action == "start":
        if not onboarding.is_complete():
            setup_result = onboarding.run()
            if setup_result != 0:
                return setup_result
        return start_daemon(args)
    if args.voice_action == "status":
        return status_daemon()
    if args.voice_action == "stop":
        return stop_daemon()

    from .voice.controller import run_once

    return run_once(args)


def _cmd_curate(args: argparse.Namespace) -> int:
    """Skill lifecycle pass: report stale, archive long-unused user skills."""
    from . import config, curator
    from .skills import build_manager
    report = curator.curate(build_manager(config.load_config()),
                            apply=not args.dry_run)
    print(curator.render_report(report))
    return 0


def _cmd_curate_memory(args: argparse.Namespace) -> int:
    from .curation_cli import cmd_curate_memory
    return cmd_curate_memory(args)


def _cmd_reindex(args: argparse.Namespace) -> int:
    """Force-rebuild the memory-palace index (mnemosyne)."""
    from . import config
    from .memory import VaultMemory
    stats = VaultMemory(config.load_config()).reindex()
    print(f"reindexed: {stats['notes']} notes, {stats['zones']} zones, "
          f"{stats['terms']} terms, {stats['stale']} stale candidate(s)")
    return 0


def _cmd_tools(args: argparse.Namespace) -> int:
    """Show the Available Tools panel and enable/disable tools (like hermes)."""
    from pathlib import Path

    from . import config
    from .llm import LLMClient
    from .memory import VaultMemory
    from .skills import build_manager
    from .tools import ToolContext, build_tool_groups
    from .ui import BIRKIN_ART, CYAN, DIM, RED, RESET

    cfg = config.load_config()
    disabled = set(cfg.get("disabled_tools", []))
    if args.enable:
        disabled.discard(args.enable)
    if args.disable:
        disabled.add(args.disable)
    if args.enable or args.disable:
        cfg["disabled_tools"] = sorted(disabled)
        config.save_config(cfg)

    base = dict(cfg)
    base["disabled_tools"] = []
    skills, memory = build_manager(cfg), VaultMemory(cfg)
    # Inspection-only context: no network calls needed, use local-cli stub
    client = LLMClient(provider="local-cli", model="", api_key="", base_url="")
    ctx = ToolContext(cfg=base, client=client, cwd=Path.cwd(),
                      skills=skills, memory=memory)

    groups = build_tool_groups(ctx)
    rows: list[str] = []
    total = enabled = 0
    for group, tools in groups.items():
        names = [tool.name for tool in tools]
        if not names:
            rows.append(f"{CYAN}{group}{RESET}: (none)")
            continue
        marks = []
        for n in names:
            total += 1
            if group in disabled or n in disabled:
                marks.append(f"{RED}{n}{RESET}")
            else:
                enabled += 1
                marks.append(n)
        rows.append(f"{CYAN}{group}{RESET}: " + ", ".join(marks))

    # Render: ASCII art on the left, toolset rows on the right (hermes-style).
    title = f"  {RESET}Available Tools{RESET}  {DIM}({enabled}/{total} enabled){RESET}"
    print(title)
    art = list(BIRKIN_ART)
    height = max(len(art), len(rows))
    for i in range(height):
        left = f"{CYAN}{art[i]}{RESET}" if i < len(art) else " " * 42
        right = rows[i] if i < len(rows) else ""
        print(f"  {left}   {right}")
    print(f"\n{DIM}Toggle:{RESET} birkin tools --disable <name> / --enable <name>"
          f"  ·  {RED}red{RESET} = disabled")
    return 0


def _cmd_computer_use(args: argparse.Namespace) -> int:
    """Run explicit Computer Use diagnostics and setup guidance."""
    import json

    from . import config
    from .computer_use.runtime import create_service
    from .computer_use.setup_cli import setup_report

    if args.computer_use_action == "setup":
        result = setup_report()
    elif args.computer_use_action == "doctor":
        loaded_config = config.load_config()
        computer_use_policy = loaded_config.get("computer_use")
        service = create_service(
            artifact_root=config.birkin_home() / "computer-use" / "artifacts",
            policy_config=(
                computer_use_policy
                if isinstance(computer_use_policy, dict)
                else None
            ),
        )
        result = service.execute({"version": 1, "action": "doctor"})
    else:
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


_CLI_ACCESS_LEVELS = [
    ("workspace", "Writable & sandboxed to the workspace (recommended)"),
    (
        "full",
        (
            "DANGEROUS: bypass ALL approvals + sandbox "
            "(codex --dangerously-bypass-approvals-and-sandbox, "
            "claude --dangerously-skip-permissions)"
        ),
    ),
]


def _cmd_permission(args: argparse.Namespace) -> int:
    from . import config
    cfg = config.load_config()
    auto = list(cfg.get("auto_approve", []))
    if args.add:
        if args.add in ("shell", "cron"):
            print("⚠  Warning: auto-approving '" + args.add + "' lets the agent "
                  "and the unattended nightly routine run it WITHOUT asking — "
                  "including arbitrary shell commands at the configured Morpheus "
                  "time. Only do this if "
                  "you fully trust the setup.")
        if args.add not in auto:
            auto.append(args.add)
    if args.remove and args.remove in auto:
        auto.remove(args.remove)
    if args.add or args.remove:
        cfg["auto_approve"] = auto
        config.save_config(cfg)

    # CLI-agent access level (Claude Code / Codex)
    if args.access in ("workspace", "full"):
        cfg["cli_access"] = args.access
        config.save_config(cfg)
    elif args.access is None and not (args.add or args.remove):
        # Interactive picker when run with no arguments.
        from . import menu
        cur = cfg.get("cli_access", "workspace")
        labels = [f"{name} — {desc}" for name, desc in _CLI_ACCESS_LEVELS]
        di = 0 if cur == "workspace" else 1
        idx = menu.select("CLI-agent access level (Claude Code / Codex)",
                          labels, default=di)
        if idx is not None:
            chosen = _CLI_ACCESS_LEVELS[idx][0]
            if chosen == "full":
                print("⚠  'full' lets the CLI agent run ANY command and edit ANY "
                      "file with no prompts. Use only if you trust the workspace.")
            cfg["cli_access"] = chosen
            config.save_config(cfg)

    print("\nAuto-approved categories (applied without asking):")
    print("  " + (", ".join(cfg.get("auto_approve", [])) or "(none)")
          + "   (everything else is queued for `birkin review`)")
    print(f"CLI-agent access level: {cfg.get('cli_access', 'workspace')}"
          f"   (change: birkin permission --access workspace|full)")
    return 0


def _cmd_moirai(args: argparse.Namespace) -> int:
    """`birkin moirai run|list|status|resume` — deterministic workflows."""
    from .moirai import cli as moirai_cli
    action = (getattr(args, "action", "") or "list").strip()
    handlers = {"run": moirai_cli.cmd_run, "list": moirai_cli.cmd_list,
                "status": moirai_cli.cmd_status,
                "resume": moirai_cli.cmd_resume}
    handler = handlers.get(action)
    if handler is None:
        print(f"모르는 하위 명령: {action} (run|list|status|resume)")
        return 1
    return handler(args)


def _auth_claude(action: str) -> int:
    """`birkin auth claude status` — why Claude auth is or isn't working.

    Read-only: logging in is `claude /login`, which owns the browser flow.
    """
    if action not in ("status", ""):
        print("claude는 status만 지원합니다 (로그인은 `claude /login`)")
        return 1
    from . import oauth
    info = oauth.diagnose()
    print(f"claude: {oauth.explain(info)}")
    print(f"  file    : {info['path']} ({'있음' if info['file_exists'] else '없음'})")
    if "access_token_len" in info:
        print(f"  tokens  : access={info['access_token_len']}자, "
              f"refresh={info['refresh_token_len']}자")
    if info.get("subscription"):
        print(f"  plan    : {info['subscription']}")
    if info.get("env"):
        print(f"  env     : {', '.join(info['env'])}")
    return 0 if info["token"] else 1


def _cmd_auth(args: argparse.Namespace) -> int:
    """`birkin auth <codex|claude> …` — subscription backend sessions."""
    provider = (getattr(args, "provider", "") or "codex").strip()
    action = (getattr(args, "action", "") or "status").strip()
    if provider == "claude":
        return _auth_claude(action)
    if provider != "codex":
        print(f"모르는 백엔드: {provider} (codex|claude)")
        return 1
    from . import codex_oauth

    if action == "status":
        info = codex_oauth.status()
        if not info["logged_in"]:
            print("codex: 로그인 안 됨 — `birkin auth codex login`")
            return 1
        left = info["expires_in_seconds"]
        when = f"{left}s 남음" if isinstance(left, int) else "만료시각 불명"
        print(f"codex: 로그인됨 ({when})")
        print(f"  account : {info['account_id'] or '(불명)'}")
        print(f"  store   : {info['store']}")
        print(f"  backend : {info['base_url']}")
        return 0

    if action == "logout":
        print("codex: 자격증명 삭제됨" if codex_oauth.logout()
              else "codex: 삭제할 자격증명 없음")
        return 0

    try:
        if action == "login":
            codex_oauth.device_login()
        elif action == "import":
            print("주의: codex CLI 로그인은 무효화됩니다 "
                  "(refresh token 회전). 취소하려면 Ctrl+C.")
            codex_oauth.import_cli_tokens()
        else:
            print(f"모르는 하위 명령: {action} (login|status|logout|import)")
            return 1
    except codex_oauth.CodexAuthError as exc:
        print(f"codex 로그인 실패: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n취소됨.")
        return 130
    print("codex: 로그인 완료 — `birkin auth codex status` 로 확인")
    return 0


def _cmd_sessions(args: argparse.Namespace) -> int:
    """`birkin sessions [export …]` — list conversations, or export to Markdown."""
    from . import sessions_export
    if getattr(args, "action", "") != "export":
        files = sessions_export.list_sessions()
        if not files:
            print("No saved sessions.")
            return 0
        for f in files:
            print(f"  {f.stem}")
        print("\nExport one with `birkin sessions export <name> [--vault]`.")
        return 0

    export_all = bool(
        getattr(args, "all", False)
        or getattr(args, "legacy_all", False)
    )
    to_vault = bool(
        getattr(args, "vault", False)
        or getattr(args, "legacy_vault", False)
    )
    stems = ([f.stem for f in sessions_export.list_sessions()]
             if export_all else [s for s in (args.name or []) if s != "--"])
    if not stems:
        print('Which session? `birkin sessions export <name>` or --all.')
        return 1
    written, failed = [], []
    for stem in stems:
        try:
            written.append(sessions_export.export(stem, to_vault=to_vault))
        except (FileNotFoundError, ValueError, OSError) as exc:
            failed.append(f"{stem}: {exc}")
    for path in written:
        print(f"  wrote {path}")
    for line in failed:
        print(f"  skipped {line}")
    return 0 if written or not failed else 1


def _cmd_live_sessions(args: argparse.Namespace) -> int:
    """Print the ephemeral inventory of current-user agent sessions."""
    import psutil

    from .live_process_source import PsutilProcessSource
    from .live_session_render import render_live_inventory
    from .live_sessions import group_live_sessions, scan_live_sessions

    try:
        scan = scan_live_sessions(PsutilProcessSource())
    except (OSError, psutil.Error) as exc:
        print(
            f"live sessions: process enumeration failed: {exc}",
            file=sys.stderr,
        )
        return 1
    inventory = group_live_sessions(scan)
    print(render_live_inventory(inventory))
    return 0


def _cmd_odyssey(args: argparse.Namespace) -> int:
    """Seed an odyssey goal cycle; the cycle is driven via /odyssey in chat."""
    from . import config, odyssey
    goal = " ".join(t for t in (args.goal or []) if t != "--").strip()
    if not goal:
        print('Give a goal, e.g. `birkin odyssey "ship the export feature"`.')
        return 1
    s = odyssey.seed(goal, cfg=config.load_config())
    print(f"odyssey '{s['slug']}' seeded · plan: {s['boulder_path']}")
    if s["resume"]:
        print("  an active plan for this goal exists — /odyssey resumes it.")
    print("Run `/odyssey` inside `birkin` (or message your gateway) to drive "
          "the cycle.")
    return 0


def _cmd_neurosis(args: argparse.Namespace) -> int:
    """Seed a neurosis deep-interview; the interview is driven via /neurosis in chat."""
    from . import config, neurosis
    resolution = None
    kept: list[str] = []
    for tok in (args.idea or []):
        if tok == "--":
            continue
        if tok in ("--quick", "--standard", "--deep"):
            resolution = tok[2:]
        else:
            kept.append(tok)
    idea = " ".join(kept).strip()
    seed = neurosis.seed_or_resume(idea, cfg=config.load_config(), resolution=resolution)
    if seed is None:
        print('Give an idea, e.g. `birkin neurosis "a tool that ..."`.')
        return 1
    print(f"neurosis '{seed['slug']}' seeded · threshold {seed['threshold_percent']} "
          f"(source: {seed['threshold_source']}).")
    print(f"  state: {seed['state_path']}")
    print(f"  spec : {seed['spec_path']}")
    print("Run `/neurosis` inside `birkin` (or message your gateway) to drive the "
          "interview — with no idea it resumes the most recent active one.")
    return 0


def _cmd_daedalus(args: argparse.Namespace) -> int:
    """`birkin daedalus create|refresh|show|note|profile` — project doc maps."""
    from . import config, daedalus
    action = getattr(args, "daedalus_action", "")
    if action == "profile":
        print(json.dumps(daedalus.PROFILE, indent=2))
        return 0
    cfg = config.load_config()
    root = Path(getattr(args, "root", None) or Path.cwd())
    try:
        if action == "create":
            doc = daedalus.create(args.slug, root, cfg=cfg)
            print(f"daedalus '{doc['slug']}' created at {doc['token']} "
                  f"({len(doc['nodes'])} nodes)")
        elif action == "refresh":
            doc = daedalus.refresh(args.slug, root,
                                   expected_token=args.expected_token, cfg=cfg)
            print(f"daedalus '{doc['slug']}' refreshed to {doc['token']} "
                  f"({len(doc['nodes'])} nodes)")
        elif action == "note":
            doc = daedalus.add_note(args.slug, args.text,
                                    refs=tuple(args.ref or ()), cfg=cfg)
            print(f"daedalus '{doc['slug']}' noted at {doc['token']}")
        else:  # show
            doc = daedalus.load(args.slug, cfg=cfg)
            if doc is None:
                print(f"error: no document '{args.slug}'; run "
                      f"`birkin daedalus create {args.slug}` first",
                      file=sys.stderr)
                return 1
            print(daedalus.render(doc))
    except daedalus.DaedalusError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_mcp_serve(args: argparse.Namespace) -> int:
    """Run birkin as an MCP server over stdio (for `claude --mcp-config`)."""
    from . import mcp_server
    return mcp_server.serve()


def _cmd_mcp(args: argparse.Namespace) -> int:
    """Manage external MCP servers via the `claude` CLI."""
    from . import mcp
    sub = [a for a in (args.args or []) if a != "--"]
    print(mcp.scope_note())
    if not sub:
        servers, err = mcp.list_servers()
        if err:
            print(f"[birkin] {err}")
            return 1
        if not servers:
            print("No MCP servers configured. Add one with: "
                  "birkin mcp add <name> <command-or-url>")
            return 0
        print("External Claude MCP servers:")
        for s in servers:
            mark = "✓" if s.connected else "•"
            print(f"  {mark} {s.name} — {s.status}")
        return 0
    return mcp.run(sub).returncode


def _cmd_companion(args: argparse.Namespace) -> int:
    from . import companion
    try:
        return _run_companion(companion, args)
    except companion.CompanionError as exc:
        print(f"error: {exc}")
        return 1


def _run_companion(companion, args: argparse.Namespace) -> int:
    action = args.action
    if action == "bind":
        chat = args.target or args.context
        if not chat:
            print("bind needs a chat id: birkin companion bind telegram:<chat-id>")
            return 1
        record = companion.bind_context(chat, owner_id=chat.rpartition(":")[2])
        print(f"bound {record['id']} (check-ins stay off until "
              f"`companion policy --enable`)")
        return 0

    if action == "add":
        if not args.context:
            print("add needs --context telegram:<chat-id>")
            return 1
        record = companion.add_candidate(
            context_id=args.context, outcome=args.outcome,
            source_ref=args.source, next_action=args.next_action)
        print(f"{record['id']}  candidate  {record['outcome']}")
        return 0

    if action == "activate":
        if not args.target or not args.at:
            print("activate needs a commitment id and --at <ISO time>")
            return 1
        record = companion.activate(args.target, check_in_at=args.at,
                                    tz_name=args.tz,
                                    utc_offset_minutes=args.offset)
        print(f"{record['id']}  active  check-in {record['check_in_at']}")
        return 0

    if action == "answer":
        if not args.target or not args.do:
            print("answer needs a commitment id and --do <action>")
            return 1
        result = companion.answer(args.target, args.do,
                                  next_action=args.next_action,
                                  snooze_minutes=args.snooze_minutes)
        print(result["message"])
        return 0

    if action == "delete":
        if not args.target:
            print("delete needs a commitment id")
            return 1
        gone = companion.delete_commitment(args.target)
        print("deleted." if gone else "no such commitment.")
        return 0 if gone else 1

    if action == "policy":
        changes: dict[str, Any] = {}
        if args.enable:
            changes["enabled"] = True
        if args.tz and args.tz != "UTC":
            changes["timezone"] = args.tz
        if args.offset is not None:
            changes["utc_offset_minutes"] = args.offset
        if args.quiet_start and args.quiet_end:
            changes["quiet_hours"] = {"start": args.quiet_start,
                                      "end": args.quiet_end}
        if args.daily_cap is not None:
            changes["daily_cap"] = args.daily_cap
        if args.cooldown is not None:
            changes["cooldown_minutes"] = args.cooldown
        policy = (companion.set_policy(**changes) if changes
                  else companion.get_policy())
        print(json.dumps(policy, indent=2, ensure_ascii=False))
        return 0

    if action == "pause":
        companion.pause_all()
        print("proactive check-ins paused.")
        return 0

    if action == "resume":
        companion.resume()
        print("proactive check-ins resumed.")
        return 0

    if action == "events":
        for event in companion.read_events(commitment_id=args.target):
            print(f"{event['at']}  {event['type']:<22} {event['summary']}")
        return 0

    if action == "status":
        policy = companion.get_policy()
        print(f"proactive: {'on' if policy.get('enabled') else 'off'}  "
              f"tz={policy.get('timezone')}  cap={policy.get('daily_cap')}  "
              f"cooldown={policy.get('cooldown_minutes')}m")
        if not companion.tz_available():
            print("note: no IANA tz database here — using the stored UTC "
                  "offset (pip install tzdata for DST-aware times).")
        for ctx in companion.load_state()["contexts"].values():
            print(f"context {ctx['id']}  {ctx['state']}  "
                  f"proactive={ctx.get('proactive_mode')}")

    records = companion.list_commitments(context_id=args.context)
    if not records:
        print("no commitments yet.")
        return 0
    for record in records:
        print(f"{record['id']}  {record['status']:<9} "
              f"{record.get('check_in_at') or '-':<25} {record['outcome']}")
    return 0


def _cmd_cron(args: argparse.Namespace) -> int:
    from . import cron, store
    jobs = cron.load_jobs()
    if args.remove:
        try:
            ok = cron.remove_job(args.remove)
        except store.FileLockTimeout:
            print("cron store is busy; retry.")
            return 1
        print("removed." if ok else "no such job id.")
        return 0 if ok else 1
    if not jobs:
        print("No cron jobs. The nightly routine can propose some for approval.")
        return 0
    for j in jobs:
        state = "on" if j.get("enabled", True) else "off"
        print(f"{j['id']}  {cron.schedule_display(j)}  "
              f"[{state}] {j.get('type')}  {j.get('name')}")
    return 0


def _cmd_runs(args: argparse.Namespace) -> int:
    from . import store
    from .ui import CYAN, DIM, RESET
    runs = store.list_runs(limit=int(args.limit))
    if not runs:
        print("No runs recorded yet.")
        return 0
    total_tokens = 0
    for r in runs:
        usage = r.get("usage") or {}
        tok = int(usage.get("estTokens", 0) or 0)
        total_tokens += tok
        tools = ", ".join((r.get("details") or {}).get("tools") or [])
        when = str(r.get("at", ""))[:19].replace("T", " ")
        print(f"{DIM}{when}{RESET}  {CYAN}{r.get('kind'):7}{RESET} ~{tok:>5} tok  "
              f"{str(r.get('summary', ''))[:70]}")
        if tools:
            print(f"             {DIM}tools: {tools}{RESET}")
    print(f"\n{DIM}{len(runs)} run(s), ~{total_tokens} est. tokens total. "
          f"Ledger: {store.config.ledger_path()}{RESET}")
    return 0


def _cmd_budget(args: argparse.Namespace) -> int:
    from . import budget, config
    from .ui import BOLD, CYAN, DIM, RED, RESET
    cfg = config.load_config()
    st = budget.status(cfg)
    print(f"{BOLD}Token budget{RESET}  (caps: 0 = unlimited)")
    daily_flag = f"{RED}OVER{RESET}" if st["over_daily"] else f"{CYAN}ok{RESET}"
    month_flag = f"{RED}OVER{RESET}" if st["over_monthly"] else f"{CYAN}ok{RESET}"
    print(f"  today : {st['used_today']:>8} / {st['daily_cap']:<8}  [{daily_flag}]")
    print(f"  month : {st['used_month']:>8} / {st['monthly_cap']:<8}  [{month_flag}]")
    model = str(cfg.get("model") or "sonnet")
    day_usd = budget.estimate_cost_usd(st["used_today"], model)
    month_usd = budget.estimate_cost_usd(st["used_month"], model)
    print(f"\n{BOLD}At API list rates{RESET} ({model}, ~20 % output)")
    print(f"  today : ${day_usd:>8.2f}")
    print(f"  month : ${month_usd:>8.2f}")
    tiers = budget.ANNOUNCED_CREDIT_TIERS_USD
    fits = [name for name, cap in sorted(tiers.items(), key=lambda kv: kv[1])
            if month_usd <= cap]
    verdict = (f"fits the {fits[0]} credit tier (${tiers[fits[0]]}/mo)"
               if fits else "exceeds every announced credit tier")
    print(f"  {DIM}this month {verdict}.{RESET}")
    print(f"\n{DIM}Set caps via config.json: budget_tokens_daily, "
          f"budget_tokens_monthly. Cost is an estimate over recorded tokens, "
          f"not a bill — see ADR-050.{RESET}")
    return 0


def _cmd_trace(args: argparse.Namespace) -> int:
    """`birkin trace <run-id>` — print a single run record (audit trail replay)."""
    import json as _json

    from . import config as _config
    from .ui import BOLD, CYAN, DIM, RESET
    needle = (args.run_id or "").strip()
    if not needle:
        print("Give a run id (see `birkin runs`).")
        return 1
    matches = sorted(_config.runs_dir().glob(f"*{needle}*.json"))
    if not matches:
        print(f"No run matches {needle!r}.")
        return 1
    for path in matches[:5]:
        try:
            rec = _json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # a truncated/corrupt run file must not crash the whole trace
        print(f"{BOLD}── {rec.get('id')}{RESET}  {DIM}{rec.get('at','')}{RESET}  "
              f"{CYAN}{rec.get('kind')}{RESET}")
        print(f"  summary: {rec.get('summary')}")
        usage = rec.get("usage") or {}
        if usage:
            print(f"  usage  : ~{usage.get('estTokens', 0)} tok "
                  f"({usage.get('chars', 0)} chars)")
        details = rec.get("details") or {}
        if details:
            print(f"  details: {_json.dumps(details, ensure_ascii=False)[:400]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="birkin", description="Lightweight self-improving CLI agent workspace")
    p.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    sub = p.add_subparsers(dest="command")

    chatp = sub.add_parser("chat", help="interactive chat (default)")
    chatp.add_argument("--dry-run", action="store_true",
                       help="build & print the prompt packet without calling the model")
    chatp.add_argument("-m", "--message", help="message to inspect with --dry-run")
    chatp.add_argument(
        "positional_message",
        nargs="?",
        help="message to inspect with --dry-run",
    )
    chatp.set_defaults(func=_cmd_chat)

    pp = sub.add_parser("plugins", help="inspect and install signed plugin bundles")
    pps = pp.add_subparsers(dest="action", required=True)
    inspectp = pps.add_parser("inspect", help="show permissions before installation")
    inspectp.add_argument("source")
    installp = pps.add_parser("install", help="install an exact bundle version")
    installp.add_argument("source")
    installp.add_argument("--version", required=True, help="exact semantic version")
    installp.add_argument("--scope", choices=("project", "team"), default="project")
    installp.add_argument("--yes", action="store_true", help="confirm disclosed permissions")
    installp.add_argument("--upgrade", action="store_true", help="replace an existing scope pin")
    resolvep = pps.add_parser("resolve", help="show the effective project/team pin")
    resolvep.add_argument("name")
    resolvep.add_argument("--version", help="require this exact installed version")
    effectsp = pps.add_parser("effects", help="manage plugin tool effect attestations")
    effectsp.add_argument("--json", dest="effect_json", action="store_true",
                          help=argparse.SUPPRESS)
    effectsp.add_argument("effect_args", nargs=argparse.REMAINDER)
    effectsp.set_defaults(func=_cmd_plugin_effects)
    for plugin_parser in (inspectp, installp, resolvep):
        plugin_parser.add_argument("--json", action="store_true", help="machine-readable JSON")
        plugin_parser.add_argument(
            "--key", action="append", default=[], metavar="KEY_ID=HEX",
            help="trusted HMAC key (repeatable)",
        )
        plugin_parser.set_defaults(func=_cmd_plugins)

    sp = sub.add_parser("skills",
                        help="list skills, show one, `skills sync`, or `skills validate`")
    sp.add_argument("name", nargs="?",
                    help="skill name to show, or 'sync' / 'validate'")
    sp.add_argument("--from", dest="source", help="source skills dir for `skills sync`")
    sp.add_argument("--limit", type=int, default=None, help="max skills to sync")
    sp.add_argument("--force", action="store_true", help="overwrite existing mirrors")
    sp.add_argument("--verbose", action="store_true",
                    help="show warnings-only skills in `skills validate`")
    sp.add_argument("target", nargs="?",
                    help="argument for install/uninstall/scan")
    sp.add_argument("--source", help="trust source for `skills scan`")
    sp.set_defaults(func=_cmd_skills)

    wp = sub.add_parser("web", help="launch the local WebUI")
    wp.add_argument("--port", type=int, default=None)
    wp.add_argument("--no-browser", action="store_true")
    wp.set_defaults(func=_cmd_web)

    nbp = sub.add_parser(
        "native-bridge",
        help="serve the local bridge the macOS application connects to",
    )
    nb_sub = nbp.add_subparsers(dest="native_bridge_action", required=True)
    nb_serve = nb_sub.add_parser(
        "serve",
        help="serve one authenticated local endpoint until stopped",
    )
    nb_serve.add_argument(
        "--transport",
        choices=("uds", "loopback"),
        default=None,
        help="private Unix socket on POSIX or private loopback on Windows (default)",
    )
    nb_serve.add_argument(
        "--session-id",
        default=None,
        help="workspace session to serve (default: native-app)",
    )
    nb_serve.add_argument(
        "--root",
        type=Path,
        default=None,
        help="bridge state directory (default: $BIRKIN_HOME/native-bridge)",
    )
    nb_serve.set_defaults(func=_cmd_native_bridge)
    nb_probe = nb_sub.add_parser(
        "provider-probe",
        help="run one existing-account provider completion for release evidence",
    )
    nb_probe.add_argument("--provider", default="codex-cli", choices=("codex-cli",))
    nb_probe.add_argument("--model", default="default")
    nb_probe.add_argument("--output", type=Path)
    nb_probe.set_defaults(func=_cmd_native_provider_probe)

    sub.add_parser("setup", help="guided onboarding wizard").set_defaults(func=_cmd_setup)
    sub.add_parser("onboard", help="alias for setup (first-run wizard)").set_defaults(func=_cmd_setup)

    sub.add_parser(
        "gateway",
        help=(
            "run birkin as a service (HTTP / Telegram inbound; "
            "Slack / Discord send-only)"
        ),
    ).set_defaults(func=_cmd_gateway)

    p_voice = sub.add_parser(
        "voice",
        help="manage the voice daemon or run one deterministic turn",
    )
    p_voice.add_argument(
        "voice_action",
        nargs="?",
        choices=("setup", "onboard", "start", "status", "stop"),
        help="guided setup or daemon lifecycle action",
    )
    p_voice.add_argument(
        "--daemon-worker",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    p_voice.add_argument(
        "--once",
        action="store_true",
        help="capture and process exactly one command",
    )
    p_voice.add_argument(
        "--audio",
        help="wake-window 16-bit PCM WAV path",
    )
    p_voice.add_argument(
        "--transcript",
        help="wake transcript (deterministic mode)",
    )
    p_voice.add_argument(
        "--command",
        dest="voice_command",
        help="command text (deterministic mode)",
    )
    p_voice.add_argument(
        "--command-audio",
        default="",
        help="recorded command WAV (transcribed when --command is omitted)",
    )
    p_voice.add_argument(
        "--wake-seconds",
        type=float,
        default=3.0,
        help="live microphone wake-window duration",
    )
    p_voice.add_argument(
        "--command-seconds",
        type=float,
        default=8.0,
        help="live microphone command-window duration",
    )
    p_voice.add_argument(
        "--sample-rate",
        type=int,
        default=None,
        help="live microphone sample rate (default: voice.sample_rate)",
    )
    p_voice.add_argument(
        "--stt-model",
        default=None,
        help="OpenAI speech-to-text model (default: voice.stt_model)",
    )
    p_voice.add_argument(
        "--wake-phrase",
        default=None,
        help="normalized phrase required with the clap (default: voice.wake_phrase)",
    )
    p_voice.add_argument(
        "--gateway-url",
        default=None,
        help="local Birkin POST /message URL (default: voice.gateway_url)",
    )
    p_voice.add_argument(
        "--session-id",
        default=None,
        help="stable local Gateway session id (default: voice.session_id)",
    )
    p_voice.add_argument(
        "--tts-output",
        default="",
        help="write raw PCM16/24 kHz reply bytes to this path",
    )
    p_voice.add_argument(
        "--tts-model",
        default=None,
        help="OpenAI text-to-speech model (default: voice.tts_model)",
    )
    p_voice.add_argument(
        "--tts-voice",
        default=None,
        help="OpenAI text-to-speech voice (default: voice.tts_voice)",
    )
    p_voice.add_argument(
        "--tts-instructions",
        default=None,
        help="OpenAI speech style instructions (default: voice.tts_instructions)",
    )
    p_voice.add_argument(
        "--filler-text",
        default=None,
        help=(
            "short acknowledgement spoken while waiting for the Gateway "
            "(empty disables; default: voice.filler_text)"
        ),
    )
    p_voice.add_argument(
        "--no-playback",
        action="store_true",
        help="do not play synthesized PCM through the speaker",
    )
    p_voice.add_argument(
        "--background",
        action="store_true",
        help="enqueue the command and persist a durable receipt",
    )
    p_voice.add_argument(
        "--receipt-dir",
        default="",
        help="background receipt directory (default: BIRKIN_HOME/voice/jobs)",
    )
    p_voice.add_argument(
        "--background-workers",
        type=int,
        default=None,
        help="maximum workers (default: voice.background_workers)",
    )
    p_voice.add_argument(
        "--background-timeout",
        type=float,
        default=300.0,
        help="seconds to wait for this one-shot background result",
    )
    p_voice.set_defaults(func=_cmd_voice)

    tp = sub.add_parser("tools", help="list/enable/disable the agent's tools")
    tp.add_argument("--enable", help="tool name to enable")
    tp.add_argument("--disable", help="tool name to disable")
    tp.set_defaults(func=_cmd_tools)

    cup = sub.add_parser(
        "computer-use",
        help="inspect native desktop capabilities and setup guidance",
    )
    cu_sub = cup.add_subparsers(
        dest="computer_use_action",
        required=True,
    )
    cu_doctor = cu_sub.add_parser(
        "doctor",
        help="report capabilities and permissions without prompting",
    )
    cu_doctor.add_argument("--json", action="store_true")
    cu_doctor.set_defaults(func=_cmd_computer_use)
    cu_setup = cu_sub.add_parser(
        "setup",
        help="print explicit install and least-privilege permission steps",
    )
    cu_setup.add_argument("--json", action="store_true")
    cu_setup.set_defaults(func=_cmd_computer_use)

    mp = sub.add_parser("model", aliases=["models"],
                        help="choose the model (interactive, like `hermes model`)")
    mp.add_argument("name", nargs="?", help="set this model directly (skips the picker)")
    mp.set_defaults(func=_cmd_model)

    # `nightly` remains an argv-level compatibility alias so argparse does not
    # leak the supposedly hidden command as ``==SUPPRESS==`` in top-level help.
    npar = sub.add_parser(
        "morpheus",
        help="run the self-improvement routine now (Morpheus)",
    )
    npar.add_argument("--dry-run", action="store_true",
                      help="analyze but propose nothing for execution")
    npar.set_defaults(func=_cmd_morpheus)

    dp = sub.add_parser("daemon", help="run the morpheus + cron scheduler")
    dp.add_argument("--install", action="store_true",
                    help="register an OS-native daily task instead of running the loop")
    dp.set_defaults(func=_cmd_daemon)

    ap = sub.add_parser("auth", help="sign in to a subscription backend (codex)")
    ap.add_argument("provider", nargs="?", default="codex",
                    help="codex (login/status/logout/import) | claude (status)")
    ap.add_argument("action", nargs="?", default="status",
                    help="login | status | logout | import")
    ap.set_defaults(func=_cmd_auth)

    sub.add_parser("review", help="approve/reject pending proposed actions").set_defaults(func=_cmd_review)

    whq = sub.add_parser(
        "worker-hook-qa",
        help="exercise approval-gated worker continuation without side effects",
    )
    whq.add_argument("--decision", required=True, choices=["approve", "reject"])
    whq.set_defaults(func=_cmd_worker_hook_qa)

    lp = sub.add_parser(
        "lineage",
        help="list, recover, prune, or export trusted compaction snapshots",
    )
    lps = lp.add_subparsers(dest="lineage_action", required=True)
    lps.add_parser("list", help="list trusted snapshots")
    recoverp = lps.add_parser("recover", help="print one snapshot's messages")
    recoverp.add_argument("snapshot_id")
    prunep = lps.add_parser("prune", help="keep only the newest snapshots")
    prunep.add_argument("--keep", type=int, required=True)
    exportp = lps.add_parser("export", help="export one trusted snapshot")
    exportp.add_argument("snapshot_id")
    exportp.add_argument("destination")
    for lineage_parser in lps.choices.values():
        lineage_parser.set_defaults(func=_cmd_lineage)

    hp = sub.add_parser(
        "harness",
        help="the self-improvement ledger: show / history / rollback / export / refine")
    hp.add_argument("action", nargs="?", default="show",
                    choices=["show", "history", "rollback", "export", "refine"],
                    help="what to do (default: show)")
    hp.add_argument("target", nargs="*",
                    help="refinement id (rollback), path (export), or instructions (refine)")
    hp.add_argument("--scope", choices=["local", "global"], default="global",
                    help="which harness to read (default: global)")
    hp.add_argument("--session-id", default=None,
                    help="session whose local harness to read")
    hp.add_argument("--global", dest="global_scope", action="store_true",
                    help="force the global harness")
    hp.add_argument("-n", "--limit", type=int, default=None,
                    help="history: show only the last N refinements")
    hp.set_defaults(func=_cmd_harness)

    working = sub.add_parser(
        "working-memory",
        help="inspect or update structured current-session task state",
    )
    working_actions = working.add_subparsers(
        dest="working_memory_action", required=True
    )
    working_update = working_actions.add_parser(
        "update", help="merge current task facts into one session"
    )
    working_show = working_actions.add_parser(
        "show", help="show one session's current task state"
    )
    working_clear = working_actions.add_parser(
        "clear", help="delete one session's current task state"
    )
    for action in (working_update, working_show, working_clear):
        action.add_argument("--session", required=True, help="stable session id")
        action.set_defaults(func=_cmd_working_memory)
    working_update.add_argument("--goal", help="replace the current goal")
    working_update.add_argument(
        "--correction", dest="corrections", action="append", default=[],
        help="append a user correction (repeatable)",
    )
    working_update.add_argument(
        "--constraint", dest="constraints", action="append", default=[],
        help="append a constraint (repeatable)",
    )
    working_update.add_argument(
        "--decision", dest="decisions", action="append", default=[],
        help="append a decision (repeatable)",
    )
    working_update.add_argument(
        "--incomplete", action="append", default=[],
        help="append an incomplete item (repeatable)",
    )
    working_update.add_argument(
        "--evidence", action="append", default=[],
        help="append evidence (repeatable)",
    )
    working_update.add_argument(
        "--next-action", dest="next_actions", action="append", default=[],
        help="append a concrete next action (repeatable)",
    )
    working_show.add_argument(
        "--json", action="store_true", help="print the canonical JSON state"
    )

    sub.add_parser("update", help="pull new code from the repo (fast-forward only)").set_defaults(func=_cmd_update)

    cmp_p = sub.add_parser("compare", help="blind A/B: run one prompt through two models")
    cmp_p.add_argument("prompt", nargs="*", help="the prompt to compare")
    cmp_p.add_argument("--a", help="model A (default: current model)")
    cmp_p.add_argument("--b", help="model B (default: a complementary tier)")
    cmp_p.set_defaults(func=_cmd_compare)

    pp = sub.add_parser("permission", help="view/change approvals & CLI-agent access level")
    pp.add_argument("--add", help="category to auto-approve (e.g. cron)")
    pp.add_argument("--remove", help="category to require approval for")
    pp.add_argument("--access", choices=["workspace", "full"],
                    help="CLI-agent access: workspace (safe) or full (dangerous bypass)")
    pp.set_defaults(func=_cmd_permission)

    cp = sub.add_parser("cron", help="list or remove daily cron jobs")
    cp.add_argument("--remove", help="job id to remove")
    cp.set_defaults(func=_cmd_cron)

    comp = sub.add_parser(
        "companion",
        help="commitments birkin follows up on (add/activate/list/answer)")
    comp.add_argument(
        "action",
        choices=["status", "list", "bind", "add", "activate", "answer",
                 "policy", "pause", "resume", "delete", "events"],
        help="what to do")
    comp.add_argument("target", nargs="?", default="",
                      help="commitment id, or chat id for bind")
    comp.add_argument("--outcome", default="", help="what the user committed to")
    comp.add_argument("--next", dest="next_action", default="",
                      help="the next concrete step")
    comp.add_argument("--source", default="",
                      help="source reference, e.g. telegram:<chat>:<message-id>")
    comp.add_argument("--context", default="", help="context id (telegram:<chat>)")
    comp.add_argument("--at", default="", help="check-in time (ISO 8601)")
    comp.add_argument("--tz", default="UTC", help="IANA timezone name")
    comp.add_argument("--offset", type=int, default=None,
                      help="UTC offset in minutes (fallback without a tz database)")
    comp.add_argument("--do", default="",
                      choices=["", "done", "blocked", "snooze", "stop", "wrong"],
                      help="answer: how the check-in was answered")
    comp.add_argument("--snooze-minutes", type=int, default=60,
                      help="answer --do snooze: how long to wait")
    comp.add_argument("--enable", action="store_true",
                      help="policy: turn proactive check-ins on")
    comp.add_argument("--quiet-start", default="", help="policy: HH:MM")
    comp.add_argument("--quiet-end", default="", help="policy: HH:MM")
    comp.add_argument("--daily-cap", type=int, default=None,
                      help="policy: max sends per day")
    comp.add_argument("--cooldown", type=int, default=None,
                      help="policy: minutes between sends")
    comp.set_defaults(func=_cmd_companion)

    rp = sub.add_parser("runs", help="show recent run records + usage (audit log)")
    rp.add_argument("--limit", type=int, default=20)
    rp.set_defaults(func=_cmd_runs)

    sub.add_parser("budget", help="show token budget usage vs caps").set_defaults(func=_cmd_budget)

    sub.add_parser(
        "reindex",
        help="rebuild the memory-palace index (zones, terms, dynamics)",
    ).set_defaults(func=_cmd_reindex)

    cur = sub.add_parser(
        "curate",
        help="skill lifecycle pass: report stale, archive unused user skills")
    cur.add_argument("--dry-run", action="store_true",
                     help="report only; move nothing")
    cur.set_defaults(func=_cmd_curate)

    cm = sub.add_parser(
        "curate-memory",
        help="model-agnostic memory-vault curation (any provider proposes a "
             "plan; a deterministic executor applies only the safe ops)")
    cm.add_argument("--provider", default=None,
                    help="claude | codex | api | gemini | local | gemini-api "
                         "| nvidia | freellmapi (default: config provider)")
    cm.add_argument("--model", default=None)
    cm.add_argument("--dry-run", action="store_true",
                    help="propose and gate the plan, print it, change nothing")
    cm.set_defaults(func=_cmd_curate_memory)

    tp_ = sub.add_parser("trace", help="print a run record (audit replay)")
    tp_.add_argument("run_id", help="run id (or a substring) — see `birkin runs`")
    tp_.set_defaults(func=_cmd_trace)

    mcpp = sub.add_parser(
        "mcp",
        help=(
            "manage external Claude MCP servers (not inherited when "
            "egress enforcement is enabled)"
        ),
    )
    mcpp.add_argument("args", nargs=argparse.REMAINDER,
                      help="passed straight to `claude mcp` (e.g. list, add, remove, get)")
    mcpp.set_defaults(func=_cmd_mcp)

    sub.add_parser(
        "mcp-serve",
        help="run birkin as an MCP server (stdio) exposing memory/skills/propose "
             "tools — used by Morpheus and the gateway via `claude --mcp-config`"
        ).set_defaults(func=_cmd_mcp_serve)

    moi = sub.add_parser(
        "moirai",
        help="deterministic multi-agent workflows across claude / codex / API")
    moi.add_argument("action", nargs="?", default="list",
                     help="run | list | status | resume")
    moi.add_argument("script", nargs="?", default="",
                     help="workflow file or name (run); run id (status / resume)")
    moi.add_argument("--run-id", dest="run_id", default="",
                     help="run id (status / resume)")
    moi.add_argument("--bind", action="append", default=[], metavar="ROLE=SPEC",
                     help="pin a role to a model, e.g. --bind critic=claude:opus")
    moi.add_argument("--args", default="", metavar="JSON",
                     help="JSON object passed to the script as m.args")
    moi.add_argument("--defaults", action="store_true",
                     help="skip the picker; resolve bindings non-interactively")
    moi.add_argument("--bind-save", dest="bind_save", action="store_true",
                     help="save the chosen bindings as your defaults")
    moi.add_argument("--limit", type=int, default=10)
    moi.set_defaults(func=_cmd_moirai)

    ses = sub.add_parser(
        "sessions",
        help="list saved conversations, or export one as Markdown you own")
    ses.add_argument(
        "--all",
        dest="legacy_all",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    ses.add_argument(
        "--vault",
        dest="legacy_vault",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    sess = ses.add_subparsers(dest="action")
    export_session = sess.add_parser(
        "export",
        help="export saved sessions as Markdown",
    )
    export_session.add_argument(
        "name",
        nargs="*",
        help="session name(s) to export",
    )
    export_session.add_argument(
        "--all",
        action="store_true",
        help="export every saved session",
    )
    export_session.add_argument(
        "--vault",
        action="store_true",
        help="file the export in the vault's journal zone",
    )
    live_sessions = sess.add_parser(
        "live",
        help="inspect live agent sessions grouped by observed cwd",
    )
    ses.set_defaults(
        func=_cmd_sessions,
        name=[],
        all=False,
        vault=False,
    )
    export_session.set_defaults(func=_cmd_sessions)
    live_sessions.set_defaults(func=_cmd_live_sessions)

    ody = sub.add_parser(
        "odyssey",
        help="seed a goal-completion cycle (plan -> critique -> execute -> "
             "verify); then run /odyssey in chat to drive it")
    ody.add_argument("goal", nargs=argparse.REMAINDER, help="the goal")
    ody.set_defaults(func=_cmd_odyssey)

    nrp = sub.add_parser(
        "neurosis",
        help="seed a deep-interview (Socratic clarity-gating before acting); "
             "then run /neurosis in chat (REPL or gateway) to drive it")
    nrp.add_argument("idea", nargs=argparse.REMAINDER,
                     help="the vague idea (optionally --quick|--standard|--deep)")
    nrp.set_defaults(func=_cmd_neurosis)

    dae = sub.add_parser(
        "daedalus",
        help="evidence-linked project document maps: create / refresh / show / "
             "note / profile")
    dae_actions = dae.add_subparsers(dest="daedalus_action", required=True)
    dae_create = dae_actions.add_parser(
        "create", help="scan a project tree and write its first revision")
    dae_refresh = dae_actions.add_parser(
        "refresh", help="re-scan under a CAS token; human notes survive intact")
    dae_show = dae_actions.add_parser(
        "show", help="print the rendered document")
    dae_note = dae_actions.add_parser(
        "note", help="append a human note (refresh never rewrites it)")
    dae_actions.add_parser("profile", help="print the worker profile as json")
    for dae_parser in (dae_create, dae_refresh, dae_show, dae_note):
        dae_parser.add_argument("slug", help="document slug")
    for dae_parser in (dae_create, dae_refresh):
        dae_parser.add_argument("--root", default=None,
                                help="project root to scan (default: cwd)")
    dae_refresh.add_argument("--expected-token", required=True,
                             help="the token you last read, e.g. cas-2")
    dae_note.add_argument("--text", required=True, help="the note text")
    dae_note.add_argument("--ref", action="append", default=[],
                          help="node id this note references (repeatable)")
    for dae_parser in dae_actions.choices.values():
        dae_parser.set_defaults(func=_cmd_daedalus)

    return p


def _force_utf8_output() -> None:
    """Keep this CLI's non-ASCII text printable when stdout is not a UTF-8 tty.

    Windows encodes redirected output with the locale codepage (cp1252), so a
    piped ``birkin --help`` died on the single ``→`` in one help string, and any
    Korean line would have died the same way. Reconfiguring at the entry point
    fixes the whole class instead of policing individual strings.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:            # a test double or a raw stream
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    parser = build_parser()
    command_line = list(argv if argv is not None else sys.argv[1:])
    if command_line and command_line[0] == "nightly":
        command_line[0] = "morpheus"
    args = parser.parse_args(command_line)
    if not getattr(args, "command", None):
        return _cmd_chat(args)
    return args.func(args)
