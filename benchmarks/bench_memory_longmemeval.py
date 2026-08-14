"""Public LongMemEval accuracy/cost harness for Birkin's memory layer.

Unlike retrieval-only reports, this harness keeps evidence recall and the
reader's final-answer accuracy separate.  The committed mini fixture uses a
small deterministic local reader.  Public LongMemEval runs can use the same
reader for reproducibility or provide a local JSON-lines answer command.

Examples:
  python benchmarks/bench_memory_longmemeval.py
  python benchmarks/bench_memory_longmemeval.py \
      --data /path/to/longmemeval_s_cleaned.json --vector-backend sentence-transformers
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

# Direct ``python benchmarks/...`` execution puts only benchmarks/ on sys.path.
# Prefer this checkout over any older globally installed Birkin package.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from birkin.memory import VaultMemory  # noqa: E402 - direct-script path setup
from birkin.memory_semantic import SentenceTransformerBackend  # noqa: E402
from birkin.mnemosyne import slug, tokenize  # noqa: E402

CATEGORIES = (
    "single-session-user",
    "single-session-assistant",
    "single-session-preference",
    "multi-session",
    "temporal-reasoning",
    "knowledge-update",
    "abstention",
)
CONFIGURATIONS = ("lexical-only", "+vector", "+entity", "full")
FIXTURE = Path(__file__).parent / "fixtures" / "longmemeval-mini.json"


class DeterministicEmbeddingBackend:
    """Stable, dependency-free hashed vectors for fixture/CI evaluation."""

    name = "deterministic-hash-v1"
    _synonyms = {
        "automobile": "vehicle", "car": "vehicle", "owns": "owner",
        "ownership": "owner", "preferred": "preference", "prefer": "preference",
        "recommend": "recommendation", "recommended": "recommendation",
        "current": "current", "now": "current", "later": "current",
    }

    def embed(self, texts: list[str]) -> Sequence[Sequence[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * 64
            for term in tokenize(text):
                term = self._synonyms.get(term, term)
                # FNV-1a is stable across processes, unlike Python's hash().
                value = 2166136261
                for byte in term.encode("utf-8"):
                    value = (value ^ byte) * 16777619 & 0xffffffff
                vector[value % len(vector)] += 1.0
            vectors.append(vector)
        return vectors


def load_instances(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("LongMemEval input must be a JSON array")
    if not raw:
        return []
    if "notes" in raw[0]:
        instances = raw
    else:
        instances = [_from_public(item) for item in raw]
    unknown = sorted({item["category"] for item in instances} - set(CATEGORIES))
    if unknown:
        raise ValueError(f"unsupported LongMemEval categories: {unknown}")
    return instances


def _from_public(item: dict[str, Any]) -> dict[str, Any]:
    sids = [str(value) for value in item.get("haystack_session_ids") or []]
    sessions = item.get("haystack_sessions") or []
    dates = item.get("haystack_dates") or []
    notes = []
    for index, (sid, session) in enumerate(zip(sids, sessions)):
        lines = []
        for turn in session if isinstance(session, list) else []:
            if isinstance(turn, dict):
                lines.append(f"{turn.get('role', 'unknown')}: {turn.get('content', '')}")
        note: dict[str, Any] = {
            "id": sid, "title": f"Session {sid}", "body": "\n".join(lines),
        }
        if index < len(dates) and dates[index]:
            note["valid_at"] = str(dates[index])[:10]
        notes.append(note)
    category = _normalize_category(str(item.get("question_type")
                                       or item.get("category") or ""))
    qid = str(item.get("question_id") or "")
    evidence = [str(value) for value in item.get("answer_session_ids") or []]
    return {
        "id": qid, "category": category,
        "question": str(item.get("question") or ""),
        "answer": str(item.get("answer") or ""),
        "question_date": str(item.get("question_date") or "")[:10],
        "abstention": qid.endswith("_abs") or not evidence,
        "evidence_ids": evidence, "notes": notes,
    }


def _normalize_category(raw: str) -> str:
    value = raw.strip().lower().replace("_", "-")
    aliases = {
        "single-session-preferences": "single-session-preference",
        "multi-session-reasoning": "multi-session",
        "knowledge-update-reasoning": "knowledge-update",
        "temporal": "temporal-reasoning",
    }
    return aliases.get(value, value)


def _configuration(name: str) -> dict[str, Any]:
    return {
        "vault_path": "",
        "memory_vector_enabled": name in ("+vector", "full"),
        "memory_entity_enabled": name in ("+entity", "full"),
        "memory_temporal_enabled": name == "full",
    }


def evaluate(instances: list[dict[str, Any]], *,
             configurations: Sequence[str] = CONFIGURATIONS,
             retrieval_k: int = 5, context_k: int = 1,
             vector_backend: str = "deterministic",
             answer_command: str = "") -> dict[str, Any]:
    output: dict[str, Any] = {
        "meta": {
            "dataset": "fixture" if all(str(item.get("id", "")).split("-")[0]
                                          in {"ss", "preference", "multi", "temporal", "update", "abstention"}
                                          for item in instances) else "public",
            "questions": len(instances), "retrieval_k": retrieval_k,
            "context_k": context_k,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "answerer": answer_command or "deterministic-answer-line-v1",
        },
        "configurations": {},
    }
    for name in configurations:
        if name not in CONFIGURATIONS:
            raise ValueError(f"unknown configuration {name!r}")
        rows: list[dict[str, Any]] = []
        latencies: list[float] = []
        context_tokens: list[int] = []
        storage_bytes = 0
        for item in instances:
            with tempfile.TemporaryDirectory(prefix="birkin-lme-") as temp:
                cfg = {**_configuration(name), "vault_path": temp}
                backend = None
                if cfg["memory_vector_enabled"]:
                    backend = (DeterministicEmbeddingBackend()
                               if vector_backend == "deterministic"
                               else SentenceTransformerBackend(vector_backend))
                memory = VaultMemory(cfg, embedding_backend=backend)
                slug_to_id: dict[str, str] = {}
                for note in item["notes"]:
                    title = str(note.get("title") or note["id"])
                    slug_to_id[slug(title)] = str(note["id"])
                    memory.write_note(
                        title, str(note.get("body") or ""), source="benchmark",
                        links=list(note.get("links") or []),
                        valid_at=note.get("valid_at"),
                        invalid_at=note.get("invalid_at"),
                        expired_at=note.get("expired_at"),
                        supersedes=list(note.get("supersedes") or []),
                    )
                started = time.perf_counter()
                hits = memory.search(
                    str(item["question"]), limit=retrieval_k,
                    as_of=(item.get("question_date") if name == "full" else None))
                latencies.append((time.perf_counter() - started) * 1000)
                hit_ids = [slug_to_id.get(hit["title"], hit["title"]) for hit in hits]
                evidence = set(map(str, item.get("evidence_ids") or []))
                # Abstention examples have no gold evidence to retrieve.  They
                # are vacuously recall-complete; final-answer accuracy measures
                # whether the reader correctly declines to invent an answer.
                retrieved = (True if item.get("abstention")
                             else bool(evidence & set(hit_ids)))
                context = "\n".join(hit["snippet"] for hit in hits[:context_k])
                context_tokens.append(max(1, math.ceil(len(context) / 4)))
                answer = (_command_answer(answer_command, item, context)
                          if answer_command else _fixture_answer(context))
                correct = (_is_abstention(answer) if item.get("abstention")
                           else _answer_matches(answer, str(item.get("answer") or "")))
                rows.append({"category": item["category"],
                             "retrieved": retrieved, "correct": correct})
                storage_bytes += sum(path.stat().st_size for path in Path(temp).rglob("*")
                                     if path.is_file())
        categories = {category: _metrics(
            [row for row in rows if row["category"] == category])
            for category in CATEGORIES}
        output["configurations"][name] = {
            "signals": (["lexical"] + (["vector"] if name in ("+vector", "full") else [])
                        + (["entity"] if name in ("+entity", "full") else [])
                        + (["time"] if name == "full" else [])),
            "overall": _metrics(rows),
            "categories": categories,
            "cost": {
                "tokens_per_query": round(statistics.mean(context_tokens), 1)
                if context_tokens else 0.0,
                "latency_ms_p50": round(_percentile(latencies, 50), 3),
                "latency_ms_p95": round(_percentile(latencies, 95), 3),
                "storage_bytes": storage_bytes,
            },
        }
    return output


def _fixture_answer(context: str) -> str:
    match = re.search(r"\bAnswer:\s*([^\n\[]+)", context, re.IGNORECASE)
    return match.group(1).strip(" .") if match else "I don't know"


def _command_answer(command: str, item: dict[str, Any], context: str) -> str:
    payload = json.dumps({"question": item["question"], "context": context})
    completed = subprocess.run(command, input=payload, text=True, capture_output=True,
                               shell=True, check=True, timeout=120)
    return completed.stdout.strip()


def _answer_matches(actual: str, expected: str) -> bool:
    def normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9가-힣]+", " ", value.lower()).strip()

    return bool(normalize(expected)) and normalize(expected) in normalize(actual)


def _is_abstention(answer: str) -> bool:
    low = answer.lower()
    return any(value in low for value in ("don't know", "do not know", "unknown",
                                          "insufficient information"))


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    return {
        "n": n,
        "retrieval_recall": round(sum(bool(row["retrieved"]) for row in rows) / n, 3)
        if n else None,
        "answer_accuracy": round(sum(bool(row["correct"]) for row in rows) / n, 3)
        if n else None,
    }


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile / 100 * len(ordered)) - 1)
    return ordered[rank]


def _print_report(report: dict[str, Any]) -> None:
    for name, result in report["configurations"].items():
        overall = result["overall"]
        cost = result["cost"]
        print(f"{name}: retrieval={overall['retrieval_recall']:.3f} "
              f"answer={overall['answer_accuracy']:.3f} "
              f"tokens/q={cost['tokens_per_query']:.1f} "
              f"p50/p95={cost['latency_ms_p50']:.3f}/{cost['latency_ms_p95']:.3f}ms "
              f"storage={cost['storage_bytes']}B")
        for category in CATEGORIES:
            metric = result["categories"][category]
            if metric["n"]:
                print(f"  {category:29} R={metric['retrieval_recall']:.3f} "
                      f"A={metric['answer_accuracy']:.3f} n={metric['n']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=FIXTURE)
    parser.add_argument("--out", type=Path,
                        default=Path("benchmarks/results/memory-longmemeval.json"))
    parser.add_argument("--retrieval-k", type=int, default=5)
    parser.add_argument("--context-k", type=int, default=1)
    parser.add_argument("--vector-backend", default="deterministic",
                        help="deterministic or a sentence-transformers model name")
    parser.add_argument("--answer-command", default="",
                        help="local command reading {question,context} JSON on stdin")
    args = parser.parse_args()
    report = evaluate(load_instances(args.data), retrieval_k=args.retrieval_k,
                      context_k=args.context_k, vector_backend=args.vector_backend,
                      answer_command=args.answer_command)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    _print_report(report)
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
