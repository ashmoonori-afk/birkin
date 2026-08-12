"""P0-3: the nightly Morpheus pass delivers a morning digest to chat."""

from __future__ import annotations


def _cfg(tmp_path, monkeypatch, chat="42"):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    cfg = {**config.DEFAULT_CONFIG, "morpheus_deliver_chat_id": chat}
    config.save_config(cfg)
    return cfg


def test_digest_delivers_summary_with_pending_count(tmp_path, monkeypatch):
    from birkin import morpheus, scheduler, store
    cfg = _cfg(tmp_path, monkeypatch)
    store.add_pending(category="note", title="queued overnight",
                      description="", payload={}, origin="morpheus")
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(scheduler, "deliver",
                        lambda name, chat, text: sent.append(
                            (name, chat, text)) or "sent")
    morpheus._deliver_digest(cfg, "Learned two things tonight.")
    assert sent and sent[0][0] == "morpheus" and sent[0][1] == "42"
    assert "Learned two things" in sent[0][2]
    assert "검토 대기: 1건" in sent[0][2]          # /pending one tap away
    assert "/pending" in sent[0][2]


def test_digest_hides_chat_bound_workflow_count(tmp_path, monkeypatch):
    from birkin import morpheus, scheduler
    from birkin.gateway import workflow
    cfg = _cfg(tmp_path, monkeypatch)
    workflow.queue_proposal(
        workflow.WorkflowProposal("private", "chat-bound", ("run",)),
        "task",
        "99",
    )
    sent: list[str] = []
    monkeypatch.setattr(
        scheduler,
        "deliver",
        lambda _name, _chat, text: sent.append(text) or "sent",
    )

    morpheus._deliver_digest(cfg, "summary")

    assert sent == ["summary"]


def test_digest_off_when_no_chat_configured(tmp_path, monkeypatch):
    from birkin import morpheus, scheduler
    cfg = _cfg(tmp_path, monkeypatch, chat="")
    called: list = []
    monkeypatch.setattr(scheduler, "deliver",
                        lambda *a: called.append(a) or "sent")
    morpheus._deliver_digest(cfg, "summary")
    assert called == []                            # off by default


def test_digest_routes_proposal_to_only_allowlisted_telegram_chat(
        tmp_path, monkeypatch):
    from birkin import config, morpheus, scheduler
    cfg = _cfg(tmp_path, monkeypatch, chat="")
    cfg["channels"] = {
        "telegram": {"allowed_chat_ids": ["42"], "token": "tok"}}
    config.save_config(cfg)
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        scheduler,
        "deliver",
        lambda name, chat, text: sent.append((name, chat, text)) or "sent",
    )
    proposal = """```json
{"summary": "Morning proposal",
 "rationale": "Repeated workflow detected",
 "expectedOutcome": "Less manual setup tomorrow",
 "edits": [{"action": "create", "kind": "memory",
            "title": "Remember deploy ritual",
            "content": "Run make deploy before release"}]}
```"""

    morpheus._deliver_digest(config.load_config(), proposal)

    assert sent[0][:2] == ("morpheus", "42")
    card = sent[0][2]
    assert card.startswith("🧠 Morpheus 제안")
    assert "📌 Morning proposal" in card
    assert "왜 필요한가\nRepeated workflow detected" in card
    assert "기대 결과\nLess manual setup tomorrow" in card
    assert "변경 제안\n1. [memory · create] Remember deploy ritual" in card
    assert "Run make deploy before release" in card
    assert "```" not in card
    assert '{"summary"' not in card


def test_proposal_card_fits_telegram_delivery_budget():
    import json
    from birkin import morpheus
    proposal = {
        "summary": "s" * 1000,
        "rationale": "r" * 1000,
        "expectedOutcome": "o" * 1000,
        "edits": [
            {"action": "update", "kind": "memory", "title": "t" * 500,
             "content": "c" * 1000}
            for _ in range(12)
        ],
    }

    card = morpheus._proposal_card(
        f"```json\n{json.dumps(proposal)}\n```")

    assert len(card) <= 3400
    assert "```" not in card


def test_silent_summary_stays_silent(tmp_path, monkeypatch):
    # [SILENT] must reach scheduler.deliver UNMODIFIED (no pending suffix
    # appended) so its first-token check suppresses the send.
    from birkin import morpheus, scheduler, store
    cfg = _cfg(tmp_path, monkeypatch)
    store.add_pending(category="note", title="x", description="",
                      payload={}, origin="morpheus")
    sent: list[str] = []
    monkeypatch.setattr(scheduler, "deliver",
                        lambda name, chat, text: sent.append(text)
                        or "skipped-silent")
    morpheus._deliver_digest(cfg, "[SILENT] nothing durable happened")
    assert sent and sent[0].startswith("[SILENT]")


def test_scheduler_deliver_wrapper_honors_silent_and_allowlist(tmp_path,
                                                               monkeypatch):
    from birkin import config, scheduler
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    cfg = {**config.DEFAULT_CONFIG,
           "channels": {"telegram": {"allowed_chat_ids": ["42"],
                                     "token": "tok"}}}
    config.save_config(cfg)
    assert scheduler.deliver("m", "", "hi") == "none"
    assert scheduler.deliver("m", "42", "[SILENT] n/a") == "skipped-silent"
    # outbound allowlist: a stranger's chat is refused before any HTTP
    assert scheduler.deliver("m", "666", "hi").startswith("error:")
