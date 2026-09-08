from __future__ import annotations

import json
import threading
from pathlib import Path

from birkin import providers
from birkin import moirai
from birkin.moirai import bindings, engine, journal
from birkin.moirai import cli as moirai_cli
from birkin.tools import web


SCHEMA = {
    "type": "object",
    "required": ["candidates", "web_search_count", "observed_query", "provenance"],
    "properties": {
        "candidates": {"type": "array", "items": {"type": "object"}},
        "web_search_count": {"type": "integer"},
        "observed_query": {"type": "string"},
        "provenance": {"type": "string"},
    },
}


def _events(*, other_tool: bool = False,
            query: object = "SQLite WAL docs",
            queries: object = None) -> str:
    action = {"type": "search", "query": query, "queries": queries}
    items = [
        {"type": "turn.started"},
        {"type": "item.started", "item": {
            "id": "search-1", "type": "web_search",
        }},
        {
        "type": "item.completed", "item": {
            "id": "search-1", "type": "web_search",
            "action": {key: value for key, value in action.items() if value is not None},
        },
    }]
    if other_tool:
        items.append({
            "type": "item.started",
            "item": {"id": "command-1", "type": "command_execution"},
        })
    items.append({
        "type": "item.completed", "item": {
            "type": "agent_message",
            "text": json.dumps({"candidates": [{
                "axis_id": "wal", "url": "https://sqlite.org/wal.html",
                "title": "WAL",
            }]}),
        },
    })
    items.append({"type": "turn.completed"})
    return "\n".join(json.dumps(item) for item in items)


def test_codex_native_web_uses_ephemeral_isolation_and_observed_trace(
    tmp_path: Path, monkeypatch,
) -> None:
    seen = {}

    def run(argv, stdin=None, timeout=0, cwd=None, env=None, abort=None):
        seen.update(argv=argv, stdin=stdin, cwd=cwd)
        return _events(), "sensitive stderr", 0

    monkeypatch.setattr(providers.shutil, "which", lambda name: "codex")
    monkeypatch.setattr(providers, "_run", run)
    result = json.loads(providers.codex_web_discovery(
        "safe prompt", model="gpt-test", schema=SCHEMA,
        abort=threading.Event(),
    ))

    assert {"--search", "--ephemeral", "--json", "--ignore-user-config",
            "--ignore-rules", "read-only"}.issubset(seen["argv"])
    assert seen["argv"][1:7] == [
        "--search", "--disable", "shell_tool", "--disable", "unified_exec", "exec",
    ]
    assert seen["cwd"] != str(tmp_path)
    assert seen["stdin"] == "safe prompt"
    assert "safe prompt" not in seen["argv"]
    assert any(str(arg).startswith("developer_instructions=")
               for arg in seen["argv"])
    assert result["web_search_count"] == 1
    assert result["observed_query"] == "SQLite WAL docs"
    assert result["provenance"] == "model_discovered_after_web_search"


def test_codex_native_web_accepts_single_queries_action(monkeypatch) -> None:
    monkeypatch.setattr(providers.shutil, "which", lambda name: "codex")
    monkeypatch.setattr(
        providers, "_run", lambda *args, **kwargs: (
            _events(query=None, queries=["SQLite WAL docs"]), "secret", 0,
        ),
    )

    result = json.loads(providers.codex_web_discovery("safe", schema=SCHEMA))

    assert result["observed_query"] == "SQLite WAL docs"


def test_codex_native_web_preserves_bounded_query_batch(monkeypatch) -> None:
    queries = [letter * 500 for letter in "abcd"]
    monkeypatch.setattr(providers.shutil, "which", lambda name: "codex")
    monkeypatch.setattr(
        providers, "_run", lambda *args, **kwargs: (
            _events(query=None, queries=queries), "secret", 0,
        ),
    )
    result = json.loads(providers.codex_web_discovery("safe", schema=SCHEMA))
    assert result["observed_query"].splitlines() == queries
    assert result["web_search_count"] == 1


def test_codex_native_web_rejects_ambiguous_query_shapes(monkeypatch) -> None:
    monkeypatch.setattr(providers.shutil, "which", lambda name: "codex")
    cases = [
        {"query": "first", "queries": ["second"]},
        {"query": None, "queries": []},
        {"query": "first", "queries": ["first", "second"]},
        {"query": None, "queries": ["q"] * 5},
        {"query": None, "queries": ["first", " "]},
        {"query": None, "queries": [7]},
        {"query": 7, "queries": None},
    ]
    for case in cases:
        monkeypatch.setattr(
            providers, "_run", lambda *args, case=case, **kwargs: (
                _events(**case), "secret", 0,
            ),
        )
        assert providers.codex_web_discovery("safe", schema=SCHEMA) == (
            "[provider-error] codex native web: invalid tool trace (query)"
        )


def test_codex_native_web_rejects_other_tool_without_reflecting_output(
    monkeypatch,
) -> None:
    monkeypatch.setattr(providers.shutil, "which", lambda name: "codex")
    monkeypatch.setattr(
        providers, "_run",
        lambda *args, **kwargs: (_events(other_tool=True), "secret", 0),
    )
    result = providers.codex_web_discovery("safe", schema=SCHEMA)
    assert result == (
        "[provider-error] codex native web: invalid tool trace (other_tool)"
    )
    assert "secret" not in result


def test_codex_native_web_rejects_non_object_events(monkeypatch) -> None:
    monkeypatch.setattr(providers.shutil, "which", lambda name: "codex")
    for output in ("[]", "1"):
        monkeypatch.setattr(
            providers, "_run", lambda *args, output=output, **kwargs: (
                output, "secret", 0,
            ),
        )
        assert providers.codex_web_discovery("safe", schema=SCHEMA) == (
            "[provider-error] codex native web: invalid event stream"
        )


def test_codex_native_web_requires_completed_search_and_successful_terminal(
    monkeypatch,
) -> None:
    monkeypatch.setattr(providers.shutil, "which", lambda name: "codex")
    events = [json.loads(line) for line in _events().splitlines()]
    cases = [
        ([event for event in events if not (
            event.get("type") == "item.completed"
            and event.get("item", {}).get("type") == "web_search"
        )], "search_count"),
        ([*events[:-1], {"type": "turn.failed", "error": "secret"}], "terminal"),
        ([events[0], events[3], events[1], events[2], events[4]], "order"),
    ]
    for case, reason in cases:
        output = "\n".join(json.dumps(event) for event in case)
        monkeypatch.setattr(
            providers, "_run", lambda *args, output=output, **kwargs: (
                output, "secret", 0,
            ),
        )
        assert providers.codex_web_discovery("safe", schema=SCHEMA) == (
            f"[provider-error] codex native web: invalid tool trace ({reason})"
        )


def test_codex_native_web_rejects_overlong_observed_query(monkeypatch) -> None:
    monkeypatch.setattr(providers.shutil, "which", lambda name: "codex")
    monkeypatch.setattr(
        providers, "_run",
        lambda *args, **kwargs: (_events(query="x" * 501), "secret", 0),
    )
    assert providers.codex_web_discovery("safe", schema=SCHEMA) == (
        "[provider-error] codex native web: invalid tool trace (query_length)"
    )
    monkeypatch.setattr(
        providers, "_run", lambda *args, **kwargs: (
            _events(query=None, queries=["short", "x" * 501]), "secret", 0,
        ),
    )
    assert providers.codex_web_discovery("safe", schema=SCHEMA) == (
        "[provider-error] codex native web: invalid tool trace (query_length)"
    )


def test_engine_native_web_uses_existing_codex_binding_only_once(tmp_path: Path) -> None:
    source = """
meta = {'name': 'native', 'roles': {'worker': {'default': 'codex:gpt-test'}}}
def main(m):
    first = m.native_web_discover('SQLite WAL docs', schema=%r)
    second = m.native_web_discover('SQLite WAL docs', schema=%r)
    return {'first': first, 'second': second}
""" % (SCHEMA, SCHEMA)
    script = engine.load_script_source(tmp_path / "native.py", source)
    calls = []
    observed = "\n".join(letter * 500 for letter in "abcd")

    def spawn(prompt, binding, opts, cfg, **kwargs):
        calls.append((binding.provider, opts["native_web"]))
        return json.dumps({
            "candidates": [], "web_search_count": 1,
            "observed_query": observed,
            "provenance": "model_discovered_after_web_search",
        })

    outcome = engine.run_script(
        script, cfg={"moirai_max_agents": 5},
        bindings_map={"worker": bindings.Binding(
            "worker", "codex", "gpt-test", "meta",
        )},
        args={"_workspace": str(tmp_path)}, spawn=spawn,
    )

    assert outcome["result"]["first"]["web_search_count"] == 1
    assert outcome["result"]["first"]["observed_query"] == observed
    assert outcome["result"]["second"] is None
    assert calls == [("codex", True)]


def test_engine_native_web_skips_non_codex_binding(tmp_path: Path) -> None:
    source = """
meta = {'name': 'native', 'roles': {'worker': {'default': 'claude:haiku'}}}
def main(m):
    return m.native_web_discover('SQLite WAL docs', schema=%r)
""" % SCHEMA
    script = engine.load_script_source(tmp_path / "native.py", source)

    outcome = engine.run_script(
        script, cfg={}, bindings_map={"worker": bindings.Binding(
            "worker", "claude", "haiku", "meta",
        )}, args={"_workspace": str(tmp_path)},
        spawn=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()),
    )

    assert outcome["result"] is None


def test_engine_native_web_skips_enforced_egress(tmp_path: Path) -> None:
    source = """
meta = {'name': 'native', 'roles': {'worker': {'default': 'codex:gpt-test'}}}
def main(m):
    return m.native_web_discover('SQLite WAL docs', schema=%r)
""" % SCHEMA
    script = engine.load_script_source(tmp_path / "native.py", source)
    outcome = engine.run_script(
        script,
        cfg={"egress": {"enabled": True, "enforced": True}},
        bindings_map={"worker": bindings.Binding(
            "worker", "codex", "gpt-test", "meta",
        )},
        args={"_workspace": str(tmp_path)},
        spawn=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()),
    )
    assert outcome["result"] is None


def test_native_web_schema_failure_does_not_retry_provider(
    tmp_path: Path, monkeypatch,
) -> None:
    source = """
meta = {'name': 'native', 'roles': {'worker': {'default': 'codex:gpt-test'}}}
def main(m):
    return m.native_web_discover('SQLite WAL docs', schema=%r)
""" % SCHEMA
    script = engine.load_script_source(tmp_path / "native.py", source)
    calls = 0

    def discover(*args, **kwargs):
        nonlocal calls
        calls += 1
        return "{}"

    monkeypatch.setattr(providers, "codex_web_discovery", discover)
    outcome = engine.run_script(
        script, cfg={}, bindings_map={"worker": bindings.Binding(
            "worker", "codex", "gpt-test", "meta",
        )}, args={"_workspace": str(tmp_path)},
    )
    assert outcome["result"] is None
    assert calls == 1


def test_resume_does_not_replay_text_call_as_native_web(tmp_path: Path) -> None:
    source = """
meta = {'name': 'native-cache', 'roles': {'worker': {'default': 'codex:gpt-test'}}}
def main(m):
    if m.args['native']:
        return m.native_web_discover('same prompt', schema=%r)
    return m.agent('same prompt', role='worker', schema=%r)
""" % (SCHEMA, SCHEMA)
    script = engine.load_script_source(tmp_path / "native_cache.py", source)
    calls = []

    def spawn(prompt, binding, opts, cfg, **kwargs):
        calls.append(bool(opts.get("native_web")))
        return json.dumps({
            "candidates": [], "web_search_count": 1,
            "observed_query": "same prompt",
            "provenance": "model_discovered_after_web_search",
        })

    first = engine.run_script(
        script, cfg={}, args={"native": False}, spawn=spawn,
    )
    calls.clear()
    second = engine.run_script(
        script, cfg={}, args={"native": True}, spawn=spawn,
        resume_from=first["run_id"],
    )

    assert calls == [True]
    assert second["cache_hits"] == 0
    assert journal.call_key("same prompt", {"provider": "codex"}) != (
        journal.call_key("same prompt", {"provider": "codex", "native_web": True})
    )


def test_zero_source_native_recovery_is_not_repeated_for_worker_leads(
    tmp_path: Path, monkeypatch,
) -> None:
    script = moirai.load_script(moirai_cli.resolve_script_path("deep-research"))
    bound = bindings.resolve(
        script.roles,
        cli={role: "codex:gpt-test" for role in script.roles}, cfg={},
    )
    calls = {"native": 0, "fetch": []}

    failed_url = "https://example.org/unusable"
    good_url = "https://sqlite.org/wal.html"
    monkeypatch.setattr(
        web, "research_search",
        lambda query, count, ctx: {
            "query": query, "status": "ok", "results": [{"url": failed_url}],
        },
    )

    def fetch(url, ctx):
        calls["fetch"].append(url)
        if url == failed_url:
            return {"requested_url": url, "final_url": url,
                    "status": "network_error", "text": ""}
        text = "SQLite WAL permits readers while a writer appends records."
        return {
            "requested_url": url, "final_url": url, "status": "ok",
            "retrieved_at": "2026-09-08T00:00:00+00:00",
            "published_at": None, "modified_at": None,
            "content_sha256": "digest", "text": text,
            "truncated": False, "error": None, "attempts": [],
        }

    monkeypatch.setattr(web, "research_fetch", fetch)

    def spawn(prompt, binding, opts, cfg, **kwargs):
        if opts.get("native_web"):
            calls["native"] += 1
            return json.dumps({
                "candidates": [
                    {"axis_id": "wal", "url": failed_url,
                     "title": "Already attempted"},
                    {"axis_id": "wal", "url": good_url,
                     "title": "Write-Ahead Logging"},
                    {"axis_id": "locking", "url": good_url,
                     "title": "Duplicate across axes"},
                ],
                "web_search_count": 1, "observed_query": "SQLite WAL docs",
                "provenance": "model_discovered_after_web_search",
            })
        if "서로 겹치지 않는 조사 축" in prompt:
            return json.dumps({"axes": [
                {"id": "wal", "name": "WAL", "question": "WAL writers?",
                 "queries": ["SQLite WAL concurrent writers"]},
                {"id": "locking", "name": "Locking",
                 "question": "How are writers locked?",
                 "queries": ["SQLite writer locking"]},
            ]})
        if "계획 완전성 검토" in prompt:
            return json.dumps({"complete": True, "missing_questions": [],
                               "reason": "covered"})
        if "확장 리드" in prompt:
            return json.dumps({"findings": [], "leads": []})
        if "위 source_id만" in prompt:
            return json.dumps({"findings": [], "leads": ["further evidence"]})
        raise AssertionError(prompt[:120])

    outcome = moirai.run_script(
        script, cfg={"moirai_max_agents": 10}, bindings_map=bound,
        args={"question": "SQLite WAL behavior", "_workspace": str(tmp_path)},
        spawn=spawn,
    )["result"]

    assert calls == {"native": 1, "fetch": [failed_url, good_url]}
    assert outcome["source_ledger"][0]["discovery_method"] == (
        "model_discovered_after_web_search"
    )
