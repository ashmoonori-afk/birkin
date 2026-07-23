import pytest

from birkin.intents import IntentEngine


class ToolClient:
    provider = "openai"
    model = "test"

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        assert kwargs["tools"][0]["name"] == "resolve_command"
        assert kwargs["temperature"] == 0
        assert kwargs["max_tokens"] == 256
        return {"content": [{"type": "tool_use", "name": "resolve_command",
                              "input": self.payload}]}


def test_compiles_exact_tool_decision_for_candidate():
    client = ToolClient({"kind": "action", "action": "help", "argument": "", "question": ""})
    engine = IntentEngine({"natural_language_commands": "assist"}, client,
                          {"help"}, surface="repl")

    result = engine.resolve("도움말 보여줘", "repl")

    assert result.kind == "preview"
    assert result.action == "help"
    assert client.calls == 1


def test_malformed_or_extra_envelope_is_chat_without_action():
    client = ToolClient({"kind": "action", "action": "help", "argument": "", "question": "", "shell": "no"})
    engine = IntentEngine({"natural_language_commands": "assist"}, client,
                          {"help"}, surface="repl")

    result = engine.resolve("show help", "repl")

    assert result.kind == "chat"
    assert result.action == ""


def test_non_candidate_does_not_call_classifier():
    client = ToolClient({"kind": "action", "action": "help", "argument": "", "question": ""})
    engine = IntentEngine({"natural_language_commands": "assist"}, client,
                          {"help"}, surface="repl")

    result = engine.resolve("tell me a story", "repl")

    assert result.kind == "chat"
    assert client.calls == 0


def test_classifier_attempt_exposes_only_redacted_retention_contract():
    candidate = "show help project-only-phrase-42"
    client = ToolClient({"kind": "action", "action": "help", "argument": "", "question": ""})
    engine = IntentEngine({"natural_language_commands": "assist"}, client,
                          {"help"}, surface="repl")

    result = engine.resolve(candidate, "repl")

    assert result.attempted is True
    assert result.retained_text == "[redacted intent candidate]"
    assert result.retained_replacements == ((candidate, result.retained_text),)


def test_non_candidate_has_no_retention_replacement_contract():
    client = ToolClient({"kind": "action", "action": "help", "argument": "", "question": ""})
    engine = IntentEngine({"natural_language_commands": "assist"}, client,
                          {"help"}, surface="repl")

    result = engine.resolve("tell me a story", "repl")

    assert result.attempted is False
    assert result.retained_text == ""
    assert result.retained_replacements == ()


def test_cli_classifier_prompt_has_strict_envelope_catalog_and_surface_contract():
    engine = IntentEngine({"natural_language_commands": "assist"}, ToolClient({}),
                          {"restart", "help"}, surface="gateway")

    prompt = engine._cli_classifier_prompt()

    assert '"kind":"action|clarify|chat"' in prompt
    assert '"action":"string"' in prompt
    assert "Allowed canonical actions for gateway: help, restart." in prompt
    assert "Surface contract" in prompt


@pytest.mark.parametrize("provider", ["claude-cli", "codex-cli"])
def test_cli_classifiers_receive_the_contract_prompt(provider):
    class _CliClient:
        last_system = ""

        def __init__(self, **kwargs):
            self.provider = kwargs["provider"]
            self.model = kwargs["model"]
            self.api_key = kwargs["api_key"]
            self.base_url = kwargs["base_url"]
            self.cli_access = kwargs["cli_access"]
            self.cli_timeout = kwargs["cli_timeout"]
            self.cli_output_limit = kwargs["cli_output_limit"]

        def complete(self, **kwargs):
            type(self).last_system = kwargs["system"]
            return {"content": [{"type": "text", "text":
                                 '{"kind":"chat","action":"","argument":"","question":""}'}]}

    engine = IntentEngine({"natural_language_commands": "assist"},
                          _CliClient(provider=provider, model="test", api_key="cli",
                                     base_url="", cli_access="read-only", cli_timeout=45,
                                     cli_output_limit=65536),
                          {"help"}, surface="repl")

    assert engine._compile("show help")[0] is True
    assert "Allowed canonical actions for repl: help." in _CliClient.last_system
