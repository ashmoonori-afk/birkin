"""Tests for CLI argument parsing and wiring."""

import pytest

from birkin.cli.main import create_parser


class TestCreateParser:
    def test_chat_defaults(self):
        parser = create_parser()
        args = parser.parse_args(["chat"])
        assert args.command == "chat"
        assert args.provider == "anthropic"
        assert args.model is None
        assert args.session is None
        assert args.no_tools is False
        assert args.system_prompt is None

    def test_chat_provider_openai(self):
        parser = create_parser()
        args = parser.parse_args(["chat", "--provider", "openai"])
        assert args.provider == "openai"

    def test_chat_model_override(self):
        parser = create_parser()
        args = parser.parse_args(["chat", "--model", "gpt-4o-mini"])
        assert args.model == "gpt-4o-mini"

    def test_chat_session_resume(self):
        parser = create_parser()
        args = parser.parse_args(["chat", "--session", "abc123"])
        assert args.session == "abc123"

    def test_chat_no_tools_flag(self):
        parser = create_parser()
        args = parser.parse_args(["chat", "--no-tools"])
        assert args.no_tools is True

    def test_chat_system_prompt(self):
        parser = create_parser()
        args = parser.parse_args(["chat", "--system-prompt", "Be concise."])
        assert args.system_prompt == "Be concise."

    def test_chat_invalid_provider_rejected(self):
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["chat", "--provider", "gemini"])

    def test_sessions_subcommand(self):
        parser = create_parser()
        args = parser.parse_args(["sessions"])
        assert args.command == "sessions"

    def test_serve_defaults(self):
        parser = create_parser()
        args = parser.parse_args(["serve"])
        assert args.command == "serve"
        assert args.host == "127.0.0.1"
        assert args.port == 8321
        assert args.reload is False

    def test_no_subcommand_defaults_to_none(self):
        parser = create_parser()
        args = parser.parse_args([])
        assert args.command is None
