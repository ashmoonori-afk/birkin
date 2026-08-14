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
