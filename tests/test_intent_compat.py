from __future__ import annotations

import pytest


def test_repl_registry_retains_legacy_aliases() -> None:
    from birkin import slashcommands

    assert sorted(slashcommands._REGISTRY) == [
        "clear", "compact", "config", "cron", "hard-restart", "help", "learn",
        "load", "mcp", "memory", "model", "models", "morpheus", "neurosis",
        "new", "permission", "personality", "provider", "quit", "reload",
        "remember", "restart-gateway", "retry", "review", "save", "sessions",
        "skill", "skills", "soul", "system", "temp", "tools", "undo", "update",
        "vault",
    ]
    assert sorted(slashcommands._ALIASES.items()) == [
        ("compress", "compact"), ("exit", "quit"), ("interview", "neurosis"),
        ("nightly", "morpheus"), ("permissions", "permission"), ("persona", "soul"),
        ("q", "quit"), ("recall", "memory"), ("reset", "new"),
        ("restart", "restart-gateway"), ("restart-hard", "hard-restart"),
        ("upgrade", "update"),
    ]


def test_gateway_registry_retains_canonical_triggers() -> None:
    from birkin.gateway.core import _GATEWAY_COMMANDS

    assert [(name, triggers) for name, _description, triggers in _GATEWAY_COMMANDS] == [
        ("help", {"help", "commands", "start", "menu", "?"}),
        ("new", {"new", "reset"}),
        ("restart", {"restart", "restart-gateway", "restart_gateway", "restartgateway", "reload"}),
        ("hard_restart", {"hard-restart", "hard_restart", "hardrestart", "restart-hard", "restart_hard", "restarthard"}),
        ("neurosis", {"neurosis", "interview"}),
        ("models", {"models", "model"}),
        ("effort", {"effort", "reasoning"}),
        ("update", {"update", "upgrade", "pull"}),
        ("pending", {"pending", "approvals", "review"}),
        ("remind", {"remind", "cron", "schedule"}),
    ]


def test_gateway_command_mapping_routes_every_current_trigger() -> None:
    from birkin.gateway.core import _GATEWAY_COMMANDS, match_command

    for canonical, _description, triggers in _GATEWAY_COMMANDS:
        for trigger in triggers:
            assert match_command(f"/{trigger}@birkinbot argument") == (
                canonical,
                "argument",
            )
    assert match_command("/restart --hard") == ("hard_restart", "")
    assert match_command("/restart hard") == ("hard_restart", "")


@pytest.mark.parametrize("text", ["", "hello there", "/", "/unknown", "/unknown@birkinbot note"])
def test_gateway_unrecognized_input_does_not_become_a_command(text: str) -> None:
    from birkin.gateway.core import match_command

    assert match_command(text) == (None, "")


def test_argparse_retains_command_dispatches() -> None:
    from birkin import cli

    parser = cli.build_parser()
    action = next(action for action in parser._actions if action.choices)
    expected = [
        "budget", "chat", "compare", "cron", "curate", "curate-memory", "daemon",
        "gateway", "mcp", "mcp-serve", "model", "models", "morpheus", "neurosis",
        "nightly", "onboard", "permission", "reindex", "review", "runs", "setup",
        "skills", "tools", "trace", "update", "web",
    ]
    assert sorted(action.choices) == expected
    required_arguments = {"trace": ["run-id"]}
    for command in expected:
        namespace = parser.parse_args([command, *required_arguments.get(command, [])])
        assert namespace.command == command
        assert callable(namespace.func)
