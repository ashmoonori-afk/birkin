from birkin.intents import IntentEngine
from birkin.llm import LLMError
import threading


class ToolClient:
    provider = "openai"
    model = "test"

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def complete(self, **kwargs):
        self.calls += 1
        return {"content": [{"type": "tool_use", "name": "resolve_command",
                              "input": self.payload}]}


def test_unknown_nul_and_oversize_arguments_fail_closed():
    for action, argument in (("shell", "x"), ("help", "x\0"), ("help", "x" * 4097)):
        client = ToolClient({"kind": "action", "action": action, "argument": argument, "question": ""})
        engine = IntentEngine({"natural_language_commands": "assist"}, client,
                              {"help"}, surface="repl")
        result = engine.resolve("show help", "one")
        assert result.kind == "chat"
        assert result.action == ""


def test_expired_preview_does_not_execute(monkeypatch):
    client = ToolClient({"kind": "action", "action": "update", "argument": "", "question": ""})
    engine = IntentEngine({"natural_language_commands": "assist"}, client,
                          {"update"}, surface="repl")
    engine.resolve("update", "one")
    now = __import__("time").monotonic()
    monkeypatch.setattr("birkin.intents.time.monotonic", lambda: now + 301)

    assert engine.resolve("yes", "one").kind == "chat"


def test_input_over_limit_never_calls_classifier():
    client = ToolClient({"kind": "action", "action": "help", "argument": "", "question": ""})
    engine = IntentEngine({"natural_language_commands": "assist"}, client,
                          {"help"}, surface="repl")

    assert engine.resolve("show " + "x" * 8192, "one").kind == "chat"
    assert client.calls == 0


def test_audit_preview_never_persists_arbitrary_candidate_phrase():
    records = []

    def capture(*args):
        records.append(args)

    phrase = "project-only-phrase-42"
    client = ToolClient({"kind": "action", "action": "help", "argument": "", "question": ""})
    engine = IntentEngine({"natural_language_commands": "assist"}, client,
                          {"help"}, surface="repl", audit=capture)

    engine.resolve("show help " + phrase, "one")

    assert phrase not in repr(records)


def test_newer_same_key_supersedes_slow_older_classifier_result():
    started = threading.Event()
    release = threading.Event()

    class SlowClient(ToolClient):
        def complete(self, **kwargs):
            if kwargs["messages"][0]["content"][0]["text"] == "show help old":
                started.set()
                release.wait(timeout=2)
            return super().complete(**kwargs)

    client = SlowClient({"kind": "action", "action": "help", "argument": "", "question": ""})
    engine = IntentEngine({"natural_language_commands": "assist"}, client,
                          {"help"}, surface="repl", audit=None)
    old = []
    worker = threading.Thread(target=lambda: old.append(engine.resolve("show help old", "one")))
    worker.start()
    assert started.wait(timeout=1)

    newer = engine.resolve("tell me a story", "one")
    release.set()
    worker.join(timeout=2)

    assert newer.kind == "chat"
    assert old[0].kind == "chat"


def test_documented_aliases_are_candidates_but_output_stays_canonical():
    for text, action in (("upgrade", "update"), ("permissions", "permission"), ("q", "quit")):
        client = ToolClient({"kind": "action", "action": action, "argument": "", "question": ""})
        engine = IntentEngine({"natural_language_commands": "assist"}, client,
                              {"update", "permission", "quit"}, surface="repl", audit=None)
        assert engine.resolve(text, text).action == action


def test_malformed_classifier_envelope_writes_one_redacted_failure_audit():
    records = []

    def capture(*args):
        records.append(args)

    phrase = "project-only-phrase-42"
    client = ToolClient({"kind": "action", "action": "help", "argument": "", "question": "", "extra": "x"})
    engine = IntentEngine({"natural_language_commands": "assist"}, client,
                          {"help"}, surface="repl", audit=capture)

    assert engine.resolve("show help " + phrase, "one").kind == "chat"
    assert len(records) == 1
    details = records[0][2]
    assert details["outcome"] == "failure"
    assert "effect" in details and "elapsed_ms" in details
    assert phrase not in repr(records)


def test_provider_error_writes_one_redacted_failure_audit():
    records = []

    class BrokenClient(ToolClient):
        def complete(self, **kwargs):
            raise LLMError("provider unavailable")

    engine = IntentEngine({"natural_language_commands": "assist"}, BrokenClient({}),
                          {"help"}, surface="repl", audit=lambda *args: records.append(args))

    assert engine.resolve("show help", "one").kind == "chat"
    assert len(records) == 1
    assert records[0][2]["outcome"] == "failure"
