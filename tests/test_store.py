from birkin import store


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
    ledger = store.read_ledger()
    assert len(ledger) == 1
    assert ledger[0]["kind"] == "chat"
    assert ledger[0]["usage"]["estTokens"] == usage["estTokens"]


def test_unique_run_ids_same_second():
    store.save_run("chat", "one")
    store.save_run("chat", "two")
    runs = store.list_runs()
    assert len({r["id"] for r in runs}) == 2  # no collision within the same second
