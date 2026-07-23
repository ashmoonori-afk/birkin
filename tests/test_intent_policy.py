from birkin.intents import IntentEngine


class ToolClient:
    provider = "openai"
    model = "test"

    def __init__(self, payload):
        self.payload = payload

    def complete(self, **kwargs):
        return {"content": [{"type": "tool_use", "name": "resolve_command",
                              "input": self.payload}]}


def test_auto_safe_help_is_command_but_models_requires_confirmation():
    cfg = {"natural_language_commands": "auto-safe"}
    help_engine = IntentEngine(cfg, ToolClient({"kind": "action", "action": "help", "argument": "", "question": ""}), {"help", "models"}, surface="repl")
    model_engine = IntentEngine(cfg, ToolClient({"kind": "action", "action": "models", "argument": "", "question": ""}), {"help", "models"}, surface="repl")

    assert help_engine.resolve("show help", "one").kind == "command"
    assert model_engine.resolve("list models", "two").kind == "preview"


def test_natural_permission_mutation_is_rejected_without_pending_or_chat():
    client = ToolClient({"kind": "action", "action": "permission", "argument": "access full", "question": ""})
    engine = IntentEngine({"natural_language_commands": "assist"}, client,
                          {"permission"}, surface="repl")

    result = engine.resolve("set permission access full", "one")

    assert result.kind == "reject"
    assert engine.pending("one") is None


def test_confirm_is_whole_reply_and_consumed_once():
    client = ToolClient({"kind": "action", "action": "update", "argument": "", "question": ""})
    engine = IntentEngine({"natural_language_commands": "assist"}, client,
                          {"update"}, surface="repl")
    engine.resolve("update", "one")

    assert engine.resolve("yes please", "one").kind == "chat"
    engine.resolve("update", "one")
    assert engine.resolve("yes", "one").kind == "command"
    assert engine.resolve("yes", "one").kind == "chat"


def test_preview_then_korean_approval_dispatches_command():
    client = ToolClient({"kind": "action", "action": "update", "argument": "", "question": ""})
    engine = IntentEngine({"natural_language_commands": "assist"}, client,
                          {"update"}, surface="repl")

    assert engine.resolve("update", "one").kind == "preview"
    assert engine.resolve("승인", "one").kind == "command"


def test_audit_failure_fails_closed_before_preview_or_command():
    def broken_audit(*_args):
        raise OSError("disk unavailable")

    client = ToolClient({"kind": "action", "action": "update", "argument": "", "question": ""})
    engine = IntentEngine({"natural_language_commands": "assist"}, client,
                          {"update"}, surface="repl", audit=broken_audit)

    result = engine.resolve("update", "one")

    assert result.kind == "chat"
    assert engine.pending("one") is None
