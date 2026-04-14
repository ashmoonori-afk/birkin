"""Tests for CLI argument parsing and wiring."""

from birkin.cli.main import create_parser


class TestCreateParser:
    def test_defaults(self):
        parser = create_parser()
        args = parser.parse_args([])
        assert args.provider == "anthropic"
        assert args.model is None
        assert args.session is None
        assert args.list_sessions is False
        assert args.no_tools is False
        assert args.system_prompt is None

    def test_provider_openai(self):
        parser = create_parser()
        args = parser.parse_args(["--provider", "openai"])
        assert args.provider == "openai"

    def test_model_override(self):
        parser = create_parser()
        args = parser.parse_args(["--model", "gpt-4o-mini"])
        assert args.model == "gpt-4o-mini"

    def test_session_resume(self):
        parser = create_parser()
        args = parser.parse_args(["--session", "abc123"])
        assert args.session == "abc123"

    def test_list_sessions_flag(self):
        parser = create_parser()
        args = parser.parse_args(["--list-sessions"])
        assert args.list_sessions is True

    def test_no_tools_flag(self):
        parser = create_parser()
        args = parser.parse_args(["--no-tools"])
        assert args.no_tools is True

    def test_system_prompt(self):
        parser = create_parser()
        args = parser.parse_args(["--system-prompt", "Be concise."])
        assert args.system_prompt == "Be concise."

    def test_invalid_provider_rejected(self):
        parser = create_parser()
        try:
            parser.parse_args(["--provider", "gemini"])
            assert False, "Expected SystemExit"
        except SystemExit:
            pass
