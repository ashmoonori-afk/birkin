"""Multilingual retrieval benchmark for Birkin's two lexical memory engines.

Runs the public birkin-mnemosyne retrieval corpus (160 fictional gold notes in
English, Korean, Japanese, Chinese, Spanish and German; three query authors,
two of them independent) against:

  birkin    ``birkin.mnemosyne.Mnemosyne`` - the engine behind ``memory_search``
  bundled   ``birkin_mnemosyne.Mnemosyne`` - the package shipped in the wheel

The corpus is not vendored. Point ``--corpus-dir`` at ``benchmarks/retrieval``
of a birkin-mnemosyne checkout (tag v0.4.0):

    git clone --branch v0.4.0 https://github.com/ashmoonori-afk/birkin-mnemosyne
    python benchmarks/bench_multilingual_retrieval.py \\
        --corpus-dir birkin-mnemosyne/benchmarks/retrieval --json after.json

``--repo`` benchmarks another checkout of Birkin with this same script, which
is how a before/after pair is produced; ``--compare before.json after.json``
prints the per-slice deltas and exits 1 when any language slice got worse.
Reported numbers use the test split; one gold note per query, the gold note's
declared cross-language siblings removed from the ranking before scoring.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

K = 10
CREATED = "2026-01-01T00:00:00+00:00"
ENGINE_MODULES = {"birkin": "birkin.mnemosyne", "bundled": "birkin_mnemosyne"}
METRICS = ("r@1", "r@5", "mrr")


def rank_metrics(ranks: list[int | None]) -> dict[str, float]:
    """1-based gold ranks (None = not in the top K) -> R@1, R@5, MRR, n."""
    n = len(ranks) or 1
    return {
        "r@1": sum(r is not None and r <= 1 for r in ranks) / n,
        "r@5": sum(r is not None and r <= 5 for r in ranks) / n,
        "mrr": sum(1.0 / r for r in ranks if r is not None) / n,
        "n": float(len(ranks)),
    }


def gold_rank(hits: list[str], gold: str, siblings: frozenset[str]) -> int | None:
    ranked = [hit for hit in hits if hit not in siblings][:K]
    return ranked.index(gold) + 1 if gold in ranked else None


def write_vault(vault: Path, notes: list[Any]) -> None:
    vault.mkdir(parents=True, exist_ok=True)
    for note in notes:
        (vault / f"{note.slug}.md").write_text(
            f"---\ntitle: {note.title}\ncreated: {CREATED}\nupdated: {CREATED}\n"
            f"---\n\n{note.body}\n", encoding="utf-8")


def sidecar_bytes(vault: Path) -> int:
    return sum(path.stat().st_size for path in vault.iterdir()
               if path.name.startswith(".") and path.is_file())


def evaluate(engine: Any, queries: list[Any]) -> dict[str, Any]:
    slices: dict[str, list[int | None]] = {}
    latencies: list[float] = []
    ranks: list[list[Any]] = []
    top: list[list[str]] = []
    for query in queries:
        started = time.perf_counter()
        hits = [hit["slug"] for hit in
                engine.search(query.text, limit=K + len(query.siblings))]
        latencies.append((time.perf_counter() - started) * 1000.0)
        rank = gold_rank(hits, query.gold, query.siblings)
        ranks.append([query.split, query.author, query.lang, query.kind, rank])
        top.append(hits[:K])
        for key in (f"{query.split}/all/lang/{query.lang}",
                    f"{query.split}/all/kind/{query.kind}",
                    f"{query.split}/{query.author}/lang/{query.lang}",
                    f"{query.split}/{query.author}/kind/{query.kind}"):
            slices.setdefault(key, []).append(rank)
    latencies.sort()
    return {
        "slices": {key: rank_metrics(value) for key, value in sorted(slices.items())},
        "p50_ms": latencies[len(latencies) // 2],
        "ranks": ranks,
        "top": top,
    }


def run(corpus_dir: Path, sizes: list[int], engines: list[str]) -> list[dict[str, Any]]:
    sys.path.insert(0, str(corpus_dir))
    corpus = importlib.import_module("retrieval_corpus")
    queries = corpus.queries()
    results: list[dict[str, Any]] = []
    for size in sizes:
        with tempfile.TemporaryDirectory() as tmp:
            notes = corpus.corpus(size, seed=0)
            for name in engines:
                vault = Path(tmp) / f"vault-{name}"
                write_vault(vault, notes)
                module = importlib.import_module(ENGINE_MODULES[name])
                engine = module.Mnemosyne(vault)
                started = time.perf_counter()
                engine.rebuild()
                build_s = time.perf_counter() - started
                result = evaluate(engine, queries)
                result.update(engine=name, size=size, build_s=build_s,
                              index_bytes=sidecar_bytes(vault),
                              module_file=str(module.__file__))
                results.append(result)
    return results


def render(results: list[dict[str, Any]], split: str) -> str:
    lines: list[str] = []
    for result in results:
        lines += ["", f"### {result['engine']} / {result['size']} notes ({split} split): "
                  f"index {result['index_bytes'] / 1e6:.2f} MB, build "
                  f"{result['build_s']:.2f} s, p50 {result['p50_ms']:.1f} ms", "",
                  "| slice | n | R@1 | R@5 | MRR |", "|---|---|---|---|---|"]
        for key, metric in result["slices"].items():
            if key.startswith(f"{split}/"):
                lines.append(f"| {key[len(split) + 1:]} | {metric['n']:.0f} | "
                             f"{metric['r@1']:.3f} | {metric['r@5']:.3f} | "
                             f"{metric['mrr']:.3f} |")
    return "\n".join(lines)


def compare(before: list[dict[str, Any]], after: list[dict[str, Any]],
            split: str) -> tuple[str, list[str]]:
    """Markdown deltas plus the language slices where R@5 or MRR went down."""
    old = {(r["engine"], r["size"]): r for r in before}
    lines: list[str] = []
    worse: list[str] = []
    for result in after:
        base = old.get((result["engine"], result["size"]))
        if base is None:
            continue
        lines += ["", f"### {result['engine']} / {result['size']} notes ({split} split): "
                  f"index {base['index_bytes'] / 1e6:.2f} -> "
                  f"{result['index_bytes'] / 1e6:.2f} MB", "",
                  "| slice | n | R@1 | R@5 | MRR |", "|---|---|---|---|---|"]
        for key, metric in result["slices"].items():
            if not key.startswith(f"{split}/") or key not in base["slices"]:
                continue
            prior = base["slices"][key]
            cells = []
            for name in METRICS:
                delta = metric[name] - prior[name]
                cells.append(f"{prior[name]:.3f} -> {metric[name]:.3f} ({delta:+.3f})")
                if "/lang/" in key and name != "r@1" and delta < -1e-9:
                    worse.append(f"{result['engine']}/{result['size']}/{key} {name} "
                                 f"{delta:+.4f}")
            lines.append(f"| {key[len(split) + 1:]} | {metric['n']:.0f} | "
                         + " | ".join(cells) + " |")
        moved = {"up": 0, "down": 0}
        for (_, _, _, _, was), (row_split, _, _, _, now) in zip(base["ranks"],
                                                                result["ranks"]):
            if row_split != split or was == now:
                continue
            better = now is not None and (was is None or now < was)
            moved["up" if better else "down"] += 1
        lines += ["", f"queries that moved: {moved['up']} up, {moved['down']} down"]
    return "\n".join(lines), worse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus-dir", type=Path)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1],
                        help="Birkin checkout to benchmark (default: this one)")
    parser.add_argument("--sizes", type=int, nargs="+", default=[160, 1000])
    parser.add_argument("--engines", nargs="+", default=list(ENGINE_MODULES),
                        choices=sorted(ENGINE_MODULES))
    parser.add_argument("--split", default="test", choices=["dev", "test"])
    parser.add_argument("--json", type=Path)
    parser.add_argument("--compare", type=Path, nargs=2, metavar=("BEFORE", "AFTER"))
    args = parser.parse_args(argv)

    if args.compare:
        before, after = (json.loads(path.read_text(encoding="utf-8"))
                         for path in args.compare)
        text, worse = compare(before, after, args.split)
        print(text)
        print("\nlanguage slices that got worse:", worse or "none")
        return 1 if worse else 0
    if args.corpus_dir is None:
        parser.error("--corpus-dir is required unless --compare is used")
    sys.path.insert(0, str(args.repo.resolve()))
    results = run(args.corpus_dir.resolve(), args.sizes, args.engines)
    print(render(results, args.split))
    if args.json:
        args.json.write_text(json.dumps(results), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
