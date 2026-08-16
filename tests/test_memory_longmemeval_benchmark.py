from __future__ import annotations

import json
from pathlib import Path

from benchmarks.bench_memory_longmemeval import (CATEGORIES, evaluate,
                                                   load_instances)


def test_fixture_covers_every_longmemeval_category():
    fixture = Path("benchmarks/fixtures/longmemeval-mini.json")

    instances = load_instances(fixture)

    assert {item["category"] for item in instances} == set(CATEGORIES)
    assert all(item["notes"] for item in instances)


def test_public_instances_normalize_longmemeval_dates(tmp_path):
    dataset = tmp_path / "public.json"
    dataset.write_text(json.dumps([{
        "question_id": "public-1", "question_type": "temporal-reasoning",
        "question": "When?", "answer": "Tuesday",
        "question_date": "2023/05/30 (Tue) 23:40",
        "answer_session_ids": ["answer-1"],
        "haystack_session_ids": ["answer-1"],
        "haystack_dates": ["2023/05/20 (Sat) 02:21"],
        "haystack_sessions": [[{"role": "user", "content": "A note"}]],
    }]), encoding="utf-8")

    instance = load_instances(dataset)[0]

    assert instance["question_date"] == "2023-05-30"
    assert instance["notes"][0]["valid_at"] == "2023-05-20"


def test_report_splits_retrieval_recall_from_final_answer_accuracy():
    instances = [{
        "id": "gap", "category": "multi-session", "question": "project code",
        "answer": "violet", "evidence_ids": ["evidence"],
        "notes": [
            {"id": "distractor", "title": "Project code status",
             "body": "Project code status is discussed but not resolved."},
            {"id": "evidence", "title": "Project archive",
             "body": "project code\n\n" + "padding " * 80 + "\nAnswer: violet"},
        ],
    }]

    report = evaluate(instances, configurations=["lexical-only"],
                      retrieval_k=2, context_k=1)
    metric = report["configurations"]["lexical-only"]["categories"]["multi-session"]

    assert metric["retrieval_recall"] == 1.0
    assert metric["answer_accuracy"] == 0.0


def test_retrieval_only_report_does_not_claim_answer_accuracy():
    instances = load_instances(
        Path("benchmarks/fixtures/longmemeval-mini.json"))[:1]

    report = evaluate(instances, configurations=["lexical-only"],
                      answer_command=None)
    result = report["configurations"]["lexical-only"]

    assert report["meta"]["answerer"] is None
    assert result["overall"]["answer_accuracy"] is None
    assert result["categories"]["single-session-user"]["answer_accuracy"] is None


def test_cost_accounting_is_reported_per_configuration():
    instances = load_instances(
        Path("benchmarks/fixtures/longmemeval-mini.json"))[:2]

    report = evaluate(instances, configurations=["lexical-only", "full"])

    for name in ("lexical-only", "full"):
        cost = report["configurations"][name]["cost"]
        assert cost["tokens_per_query"] > 0
        assert cost["latency_ms_p50"] >= 0
        assert cost["latency_ms_p95"] >= cost["latency_ms_p50"]
        assert cost["storage_bytes"] > 0
    assert report["configurations"]["full"]["signals"] == [
        "lexical", "vector", "entity", "time"]


def test_json_output_is_serializable():
    report = evaluate(load_instances(
        Path("benchmarks/fixtures/longmemeval-mini.json"))[:1],
        configurations=["lexical-only"])

    json.dumps(report)
