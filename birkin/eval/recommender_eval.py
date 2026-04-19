"""Evaluate recommender quality against labeled scenarios."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from birkin.core.workflow.recommender import WorkflowRecommender
from birkin.memory.event_store import EventStore
from birkin.memory.events import RawEvent

logger = logging.getLogger(__name__)


async def evaluate_recommender(
    dataset_path: str | Path,
) -> dict[str, Any]:
    """Run recommender against evaluation dataset.

    Returns precision, recall, and failure details.
    """
    dataset = Path(dataset_path)
    scenarios = [json.loads(line) for line in dataset.read_text().strip().splitlines()]

    total = len(scenarios)
    true_pos = 0
    true_neg = 0
    false_pos = 0
    false_neg = 0
    failures: list[dict] = []

    for scenario in scenarios:
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(db_path=Path(tmp) / "eval.db")

            # Seed events
            for ev_spec in scenario["events"]:
                count = ev_spec.get("count", 1)
                for i in range(count):
                    if ev_spec["type"] == "tool_call":
                        store.append(
                            RawEvent(
                                session_id=f"eval-{i}",
                                event_type="tool_call",
                                payload={"name": ev_spec["name"]},
                            )
                        )
                    elif ev_spec["type"] == "user_message":
                        store.append(
                            RawEvent(
                                session_id=f"eval-{i}",
                                event_type="user_message",
                                payload={"content": ev_spec["content"]},
                            )
                        )

            rec = WorkflowRecommender(event_store=store)
            suggestions = await rec.suggest(top_k=5)

            expect_match = scenario.get("expect_match")
            expect_min = scenario.get("expect_min", 0)

            if expect_match is None:
                # Expect no suggestions
                if len(suggestions) == 0:
                    true_neg += 1
                else:
                    false_pos += 1
                    failures.append(
                        {
                            "id": scenario["id"],
                            "expected": "no suggestions",
                            "got": len(suggestions),
                        }
                    )
            else:
                # Expect at least expect_min suggestions matching keyword
                matched = [
                    s
                    for s in suggestions
                    if expect_match.lower() in s.description.lower() or expect_match.lower() in s.title.lower()
                ]
                if len(matched) >= 1 and len(suggestions) >= expect_min:
                    true_pos += 1
                else:
                    false_neg += 1
                    failures.append(
                        {
                            "id": scenario["id"],
                            "expected": f">={expect_min} matching '{expect_match}'",
                            "got": len(suggestions),
                            "titles": [s.title for s in suggestions],
                        }
                    )

            store.close()

    precision = true_pos / (true_pos + false_pos) if (true_pos + false_pos) > 0 else 1.0
    recall = true_pos / (true_pos + false_neg) if (true_pos + false_neg) > 0 else 1.0

    return {
        "total": total,
        "true_positive": true_pos,
        "true_negative": true_neg,
        "false_positive": false_pos,
        "false_negative": false_neg,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "failures": failures,
    }
