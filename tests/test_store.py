import json

from birkin import config, store


def test_save_and_list_runs():
    store.save_run("nightly", "did things", {"k": 1})
    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0]["kind"] == "nightly"
    assert runs[0]["summary"] == "did things"


def test_pending_lifecycle():
    rec = store.add_pending(category="cron", title="t", description="d",
                            payload={"a": 1})
    assert store.get_pending(rec["id"])["status"] == "pending"
    assert len(store.list_pending()) == 1
    store.resolve_pending(rec["id"], "approved")
    assert store.list_pending() == []
    assert store.get_pending(rec["id"])["status"] == "approved"


def test_status_roundtrip():
    store.write_status({"daemon": True, "next_nightly": "2026-05-29T04:00:00"})
    st = store.read_status()
    assert st["daemon"] is True
    assert "heartbeat" in st
    store.clear_status()
    assert store.read_status() == {"daemon": False}


def test_activity_log_recent():
    store.append_activity("chat: hello")
    text = store.read_recent_activity(hours=24)
    assert "chat: hello" in text


def test_estimate_usage():
    u = store.estimate_usage("abcd", "ef gh")  # 9 chars, 3 words
    assert u["chars"] == 9
    assert u["words"] == 3
    assert u["estTokens"] == (9 + 3) // 4


def test_save_run_records_usage_and_appends_ledger():
    usage = store.estimate_usage("prompt here", "reply text")
    store.save_run("chat", "did a thing", details={"tools": ["read_file"]}, usage=usage)
    runs = store.list_runs()
    assert runs[0]["usage"]["estTokens"] == usage["estTokens"]
    assert runs[0]["details"]["tools"] == ["read_file"]
    lines = config.ledger_path().read_text(encoding="utf-8").splitlines()
    ledger = [json.loads(line) for line in lines if line.strip()]
    assert len(ledger) == 1
    assert ledger[0]["kind"] == "chat"
    assert ledger[0]["usage"]["estTokens"] == usage["estTokens"]


def test_unique_run_ids_same_second():
    store.save_run("chat", "one")
    store.save_run("chat", "two")
    runs = store.list_runs()
    assert len({r["id"] for r in runs}) == 2  # no collision within the same second


def test_list_runs_skips_non_run_json_before_limit():
    valid = {
        "id": "run-a",
        "kind": "chat",
        "at": "2026-07-12T09:05:00+09:00",
        "summary": "done",
        "usage": {},
        "details": {},
    }
    fixtures = {
        "zzzz-invalid.json": "not-json",
        "zzzy-list.json": "[]",
        "zzzx-registry.json": json.dumps(
            {"owner": 4242, "children": [4343], "updated": "2026-07-13"}
        ),
        "zzzw-incomplete.json": json.dumps({"id": "bad", "kind": "chat"}),
        "20260712-valid.json": json.dumps(valid),
    }
    for name, body in fixtures.items():
        (config.runs_dir() / name).write_text(body, encoding="utf-8")

    assert store.list_runs(limit=1) == [valid]


def test_list_runs_requires_run_shape():
    assert store._is_run_record(
        {"id": "1", "kind": "chat", "at": "now", "summary": ""}
    )
    assert not store._is_run_record([])
    assert not store._is_run_record({"id": "1", "kind": "chat", "at": "now"})
    assert not store._is_run_record(
        {"id": "", "kind": "chat", "at": "now", "summary": "done"}
    )
    assert not store._is_run_record(
        {"id": "1", "kind": "chat", "at": "now", "summary": 3}
    )


def test_write_json_uses_unique_tmp_name(tmp_path, monkeypatch):
    # Concurrent writers to the SAME path must not collide on a fixed tmp name;
    # the temp gets a per-process unique suffix and is consumed by os.replace.
    import json
    import os
    seen = []
    real = store.os.replace

    def spy(src, dst):
        seen.append(str(src))
        return real(src, dst)

    monkeypatch.setattr(store.os, "replace", spy)
    p = tmp_path / "x.json"
    store._write_json(p, {"a": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
    assert not list(tmp_path.glob("*.tmp"))            # tmp consumed, none left
    assert seen and seen[0].endswith(".tmp")
    assert str(os.getpid()) in seen[0]                 # unique per process
