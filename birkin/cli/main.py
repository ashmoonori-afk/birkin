"""CLI entry point for Birkin agent."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown

from birkin import __version__
from birkin.core.agent import Agent
from birkin.core.providers import create_provider
from birkin.core.session import SessionStore
from birkin.memory.wiki import WikiMemory
from birkin.tools.loader import load_tools

console = Console()


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def create_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="birkin",
        description="Birkin -- AI agent CLI",
    )
    sub = parser.add_subparsers(dest="command")

    # ── birkin chat ──
    chat_p = sub.add_parser("chat", help="Interactive chat REPL")
    chat_p.add_argument(
        "--provider",
        choices=["openai", "anthropic"],
        default="anthropic",
        help="LLM provider (default: anthropic)",
    )
    chat_p.add_argument("--model", type=str, default=None, help="Model name override")
    chat_p.add_argument("--session", type=str, default=None, help="Resume a session by ID")
    chat_p.add_argument("--no-tools", action="store_true", help="Disable tool loading")
    chat_p.add_argument("--system-prompt", type=str, default=None, help="Override system prompt")

    # ── birkin sessions ──
    sub.add_parser("sessions", help="List saved sessions")

    # ── birkin mcp ──
    mcp_p = sub.add_parser("mcp", help="MCP server commands")
    mcp_sub = mcp_p.add_subparsers(dest="mcp_command")
    mcp_serve_p = mcp_sub.add_parser("serve", help="Start Birkin as an MCP server (stdio)")
    mcp_serve_p.add_argument("--no-tools", action="store_true", help="Don't expose built-in tools")
    mcp_serve_p.add_argument("--memory-dir", type=str, default="./memory", help="Wiki memory directory")

    # ── birkin eval ──
    eval_p = sub.add_parser("eval", help="Evaluation framework commands")
    eval_sub = eval_p.add_subparsers(dest="eval_command")

    eval_run_p = eval_sub.add_parser("run", help="Run eval dataset against a provider")
    eval_run_p.add_argument("dataset", type=str, help="Path to JSONL dataset file")
    eval_run_p.add_argument(
        "--provider",
        type=str,
        default="anthropic",
        help="Provider name or model ID (default: anthropic)",
    )
    eval_run_p.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to save results (default: eval_results)",
    )
    eval_run_p.add_argument(
        "--memory",
        action="store_true",
        default=False,
        help="Enable memory-aware eval (ingest memory_setup per case)",
    )

    eval_list_p = eval_sub.add_parser("list", help="List saved eval results")
    eval_list_p.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory with saved results (default: eval_results)",
    )

    eval_diff_p = eval_sub.add_parser("diff", help="Compare two eval result files")
    eval_diff_p.add_argument("file_a", type=str, help="Baseline result file (JSONL)")
    eval_diff_p.add_argument("file_b", type=str, help="Current result file (JSONL)")

    # ── birkin export ──
    export_p = sub.add_parser("export", help="Export workspace data to a portable archive")
    export_p.add_argument("--output", type=str, default=None, help="Output file path")
    export_p.add_argument("--password", type=str, default=None, help="Encrypt archive with password")

    # ── birkin import ──
    import_p = sub.add_parser("import", help="Restore workspace data from an archive")
    import_p.add_argument("archive", type=str, help="Path to .zip or .birkin archive")
    import_p.add_argument("--password", type=str, default=None, help="Decrypt archive with password")
    import_p.add_argument("--force", action="store_true", help="Overwrite existing files without prompting")

    # ── birkin skill ──
    skill_p = sub.add_parser("skill", help="Manage installed skills")
    skill_sub = skill_p.add_subparsers(dest="skill_command")
    skill_install_p = skill_sub.add_parser("install", help="Install a skill from a git repository")
    skill_install_p.add_argument("git_url", type=str, help="Git repository URL")
    skill_sub.add_parser("list", help="List installed skills")
    skill_remove_p = skill_sub.add_parser("remove", help="Remove an installed skill")
    skill_remove_p.add_argument("name", type=str, help="Skill name to remove")

    # ── birkin serve (default) ──
    serve_p = sub.add_parser("serve", help="Start the web UI and API server (default)")
    serve_p.add_argument("--host", type=str, default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    serve_p.add_argument("--port", type=int, default=8321, help="Bind port (default: 8321)")
    serve_p.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    return parser


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------


def repl(agent: Agent) -> None:
    """Interactive read-eval-print loop."""
    console.print(
        f"[bold]Birkin[/bold] v{__version__}  |  "
        f"provider=[cyan]{agent.provider.name}[/cyan]  "
        f"model=[cyan]{agent.provider.model}[/cyan]"
    )
    console.print("Type [bold]/quit[/bold] to exit.\n")

    while True:
        try:
            user_input = console.input("[bold green]> [/bold green]")
        except (EOFError, KeyboardInterrupt):
            console.print("\nBye.")
            break

        text = user_input.strip()
        if not text:
            continue
        if text in ("/quit", "/exit", "/q"):
            console.print("Bye.")
            break

        try:
            response = agent.chat(text)
            console.print(Markdown(response))
            console.print()
        except NotImplementedError as exc:
            console.print(f"[red]Provider not yet implemented:[/red] {exc}\n")
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, OSError) as exc:
            console.print(f"[red]Error:[/red] {exc}\n")


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_chat(args: argparse.Namespace) -> None:
    """Handle ``birkin chat``."""
    store = SessionStore()

    # Build model ID from provider + optional model override
    model_id = args.model or f"{args.provider}/default"
    if "/" not in model_id:
        model_id = f"{args.provider}/{model_id}"
    provider = create_provider(model_id)

    tools = [] if args.no_tools else load_tools()

    wiki = WikiMemory(root="./memory")
    wiki.init()

    agent = Agent(
        provider=provider,
        tools=tools,
        session_store=store,
        session_id=args.session,
        system_prompt=args.system_prompt,
        memory=wiki,
    )

    repl(agent)
    store.close()


def cmd_sessions(_args: argparse.Namespace) -> None:
    """Handle ``birkin sessions``."""
    store = SessionStore()
    sessions = store.list_sessions()
    if not sessions:
        console.print("[dim]No saved sessions.[/dim]")
    else:
        for s in sessions:
            count = store.get_message_count(s.id)
            console.print(f"  [bold]{s.id}[/bold]  {s.created_at:%Y-%m-%d %H:%M}  ({count} msgs)")
    store.close()


def cmd_mcp(args: argparse.Namespace) -> None:
    """Handle ``birkin mcp serve`` — start Birkin as an MCP server on stdio."""
    import asyncio

    from birkin.mcp.server import run_stdio_server
    from birkin.tools.loader import load_tools as load_builtin_tools

    mcp_command = getattr(args, "mcp_command", "serve")
    if mcp_command != "serve":
        console.print("[red]Unknown mcp subcommand.[/red] Use: birkin mcp serve")
        sys.exit(1)

    tools = None if not args.no_tools else []
    if tools is None:
        tools = load_builtin_tools()

    memory_dir = getattr(args, "memory_dir", "./memory")
    wiki = WikiMemory(root=memory_dir)
    wiki.init()

    asyncio.run(run_stdio_server(tools=tools, memory=wiki))


def cmd_eval(args: argparse.Namespace) -> None:
    """Handle ``birkin eval`` subcommands (run, list, diff)."""
    import asyncio

    from birkin.eval.cli import cmd_eval_diff, cmd_eval_list, cmd_eval_run

    eval_command = getattr(args, "eval_command", None)
    if eval_command is None:
        console.print("[red]Usage:[/red] birkin eval {run,list,diff}")
        sys.exit(1)

    if eval_command == "run":
        asyncio.run(
            cmd_eval_run(
                dataset_path=args.dataset,
                provider_name=args.provider,
                output_dir=args.output_dir,
                use_memory=getattr(args, "memory", False),
            )
        )
    elif eval_command == "list":
        cmd_eval_list(output_dir=args.output_dir)
    elif eval_command == "diff":
        cmd_eval_diff(baseline_path=args.file_a, current_path=args.file_b)
    else:
        console.print(f"[red]Unknown eval subcommand:[/red] {eval_command}")
        sys.exit(1)


def cmd_export(args: argparse.Namespace) -> None:
    """Handle ``birkin export``."""
    from birkin.cli.backup import export_archive

    try:
        result = export_archive(
            output_path=args.output,
            password=args.password,
        )
        console.print(f"[green]Exported[/green] workspace to [bold]{result}[/bold]")
    except Exception as exc:
        console.print(f"[red]Export failed:[/red] {exc}")
        sys.exit(1)


def cmd_import(args: argparse.Namespace) -> None:
    """Handle ``birkin import``."""
    from birkin.cli.backup import import_archive

    try:
        summary = import_archive(
            archive_path=args.archive,
            password=args.password,
        )
        console.print("[green]Import complete.[/green]")
        console.print(f"  Files restored : {summary['files_restored']}")
        console.print(f"  Sessions DB    : {'yes' if summary['sessions_db'] else 'no'}")
        console.print(f"  Wiki pages     : {summary['wiki_pages']}")
        console.print(f"  Config         : {'yes' if summary['config'] else 'no'}")
    except FileNotFoundError as exc:
        console.print(f"[red]Not found:[/red] {exc}")
        sys.exit(1)
    except ValueError as exc:
        console.print(f"[red]Decryption error:[/red] {exc}")
        sys.exit(1)
    except Exception as exc:
        console.print(f"[red]Import failed:[/red] {exc}")
        sys.exit(1)


def cmd_skill(args: argparse.Namespace) -> None:
    """Handle ``birkin skill`` subcommands (install, list, remove)."""
    from pathlib import Path

    from rich.table import Table

    from birkin.skills.loader import SkillLoader

    skill_command = getattr(args, "skill_command", None)
    if skill_command is None:
        console.print("[red]Usage:[/red] birkin skill {install,list,remove}")
        sys.exit(1)

    loader = SkillLoader(Path("skills"))

    if skill_command == "install":
        try:
            skill = loader.install_from_git(args.git_url)
            console.print(
                f"[green]Installed[/green] skill [bold]{skill.name}[/bold] "
                f"v{skill.spec.version} — {skill.spec.description}"
            )
        except ValueError as exc:
            console.print(f"[red]Install failed:[/red] {exc}")
            sys.exit(1)
        except RuntimeError as exc:
            console.print(f"[red]Install failed:[/red] {exc}")
            sys.exit(1)

    elif skill_command == "list":
        skills = loader.discover()
        if not skills:
            console.print("[dim]No skills installed.[/dim]")
            return

        table = Table(title="Installed Skills")
        table.add_column("Name", style="bold")
        table.add_column("Version", style="cyan")
        table.add_column("Description")
        for skill in skills:
            table.add_row(skill.name, skill.spec.version, skill.spec.description)
        console.print(table)

    elif skill_command == "remove":
        try:
            removed = loader.uninstall(args.name)
            if removed:
                console.print(f"[green]Removed[/green] skill [bold]{args.name}[/bold]")
            else:
                console.print(f"[yellow]Skill not found:[/yellow] {args.name}")
                sys.exit(1)
        except ValueError as exc:
            console.print(f"[red]Invalid skill name:[/red] {exc}")
            sys.exit(1)

    else:
        console.print(f"[red]Unknown skill subcommand:[/red] {skill_command}")
        sys.exit(1)


def cmd_serve(args: argparse.Namespace) -> None:
    """Handle ``birkin serve`` — start FastAPI + uvicorn and open browser."""
    import os
    import threading
    import time
    import webbrowser

    import uvicorn

    # Auth token check
    auth_token = os.getenv("BIRKIN_AUTH_TOKEN")
    is_localhost = args.host in ("127.0.0.1", "localhost", "::1")

    if not auth_token and not is_localhost:
        console.print(
            "[red]ERROR:[/red] BIRKIN_AUTH_TOKEN must be set when binding to a non-localhost address.\n"
            "Set the variable in your .env file or environment, then try again."
        )
        sys.exit(1)

    if not auth_token and is_localhost:
        console.print("[yellow][birkin] Running in dev mode (no auth)[/yellow]")

    url = f"http://{args.host}:{args.port}"
    console.print(f"[bold]Birkin[/bold] WebUI starting on [cyan]{url}[/cyan]\nPress [bold]Ctrl+C[/bold] to stop.\n")

    # Show API key status
    anthropic_ok = bool(os.getenv("ANTHROPIC_API_KEY"))
    openai_ok = bool(os.getenv("OPENAI_API_KEY"))
    if anthropic_ok:
        console.print("  [green]ANTHROPIC_API_KEY[/green]  configured")
    else:
        console.print("  [red]ANTHROPIC_API_KEY[/red]  not set")
    if openai_ok:
        console.print("  [green]OPENAI_API_KEY[/green]    configured")
    else:
        console.print("  [dim]OPENAI_API_KEY[/dim]    not set")

    if not anthropic_ok and not openai_ok:
        console.print(
            "\n[yellow]No API keys found.[/yellow] "
            "Copy [bold].env.example[/bold] to [bold].env[/bold] and add your key.\n"
        )

    def _open_browser() -> None:
        time.sleep(1.5)
        webbrowser.open(url)

    threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(
        "birkin.gateway.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for the ``birkin`` console script."""
    load_dotenv()

    parser = create_parser()
    args = parser.parse_args()

    handlers = {
        "chat": cmd_chat,
        "sessions": cmd_sessions,
        "mcp": cmd_mcp,
        "eval": cmd_eval,
        "export": cmd_export,
        "import": cmd_import,
        "skill": cmd_skill,
        "serve": cmd_serve,
    }

    command = args.command or "serve"
    handler = handlers.get(command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    # When no subcommand is given, argparse won't populate subcommand-specific
    # attrs. Fill in defaults so the handler works for bare ``birkin``.
    if args.command is None:
        if command == "serve":
            args.host = "127.0.0.1"
            args.port = 8321
            args.reload = False
        elif command == "chat":
            args.provider = "anthropic"
            args.model = None
            args.session = None
            args.no_tools = False
            args.system_prompt = None

    handler(args)


if __name__ == "__main__":
    main()
