"""CLI entry point for Birkin agent."""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown

from birkin.core.agent import Agent
from birkin.core.providers import create_provider
from birkin.core.session import SessionStore
from birkin.tools.loader import load_tools

console = Console()


def create_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="birkin",
        description="Birkin -- AI agent CLI",
    )
    parser.add_argument(
        "--provider",
        choices=["openai", "anthropic"],
        default="anthropic",
        help="LLM provider (default: anthropic)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model name override",
    )
    parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="Resume a session by ID",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="List saved sessions and exit",
    )
    parser.add_argument(
        "--no-tools",
        action="store_true",
        help="Disable tool loading",
    )
    parser.add_argument(
        "--system-prompt",
        type=str,
        default=None,
        help="Override the default system prompt",
    )
    return parser


def repl(agent: Agent) -> None:
    """Interactive read-eval-print loop."""
    console.print(
        f"[bold]Birkin[/bold] v0.1.0  |  "
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
            console.print(f"[red]Provider not yet implemented:[/red] {exc}")
            console.print("[dim]Waiting on BRA-59 for provider backends.[/dim]\n")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Error:[/red] {exc}\n")


def main() -> None:
    """Entry point for the ``birkin`` console script."""
    load_dotenv()

    parser = create_parser()
    args = parser.parse_args()

    store = SessionStore()

    if args.list_sessions:
        sessions = store.list_all()
        if not sessions:
            console.print("[dim]No saved sessions.[/dim]")
        else:
            for s in sessions:
                console.print(
                    f"  [bold]{s.id}[/bold]  "
                    f"{s.created_at:%Y-%m-%d %H:%M}  "
                    f"({s.message_count} msgs)"
                )
        return

    provider = create_provider(args.provider, model=args.model)
    tools = [] if args.no_tools else load_tools()

    session = store.load(args.session) if args.session else store.create()

    agent = Agent(
        provider=provider,
        tools=tools,
        session=session,
        system_prompt=args.system_prompt,
    )

    repl(agent)
    store.save(session)


if __name__ == "__main__":
    main()
