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
        except Exception as exc:  # noqa: BLE001
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


def cmd_serve(args: argparse.Namespace) -> None:
    """Handle ``birkin serve`` — start FastAPI + uvicorn and open browser."""
    import os
    import threading
    import time
    import webbrowser

    import uvicorn

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
