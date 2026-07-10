"""Real-vault experiment: does curation improve retrieval on REAL notes?

Addresses the review's two core criticisms in one harness:
(1) claim-experiment mismatch — the paper claims a personal *note vault* but
    benchmarks session retrieval; here the corpus IS a real note vault
    (the user's actual project markdown, Korean/English mixed), and
(2) missing causal link — curation and retrieval were benchmarked
    independently; here we measure retrieval BEFORE and AFTER a real
    CurationPlan/1 pass on the same vault with a frozen query set.

Design (contamination-aware, review §5):
- The corpus was never used to develop any prompt (independent test set).
- Queries are generated ONCE (paraphrase-style, by an LLM that sees each
  note), frozen to disk, and reused verbatim across conditions — no adaptive
  tuning between conditions.
- Conditions: A) raw inbox, BM25 search; B) after one sonnet CurationPlan/1
  pass: same search, PLUS link-expansion retrieval (top-3 hits expanded with
  their wikilink neighbors) to measure what links actually buy.
- Also reported: zones formed, links created, graph density (review §8),
  archive/protected actions.

Usage:
  python benchmarks/bench_real_vault.py --source <your-notes-dir>
      [--queries 40] [--provider claude --model sonnet] [--skip-curation]
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

from birkin import config, curation, mnemosyne, providers
from birkin.memory import VaultMemory
from birkin.mnemosyne import slug

RES = Path("benchmarks/results")
QUERY_FILE = RES / "realvault-queries.json"

QUERY_GEN_PROMPT = """You will write ONE search query per note, as a user who
half-remembers the note would type it. Rules:
- Match the note's language (Korean note -> Korean query).
- PARAPHRASE: do not copy a phrase verbatim from the note; use different
  wording for the same meaning where possible.
- 4-10 words, no punctuation, no note title words when avoidable.
Return ONLY a JSON object: {{"queries": [{{"slug": "...", "query": "..."}}]}}

Notes:
{notes}
"""


def ingest(source: Path, vault_dir: Path) -> list[dict]:
    """Copy real .md files into a fresh vault as inbox notes (read-only on
    the source). Returns [{slug, title, chars}]."""
    mem = VaultMemory({"vault_path": str(vault_dir)})
    seen: set[str] = set()
    notes = []
    for f in sorted(source.rglob("*.md")):
        if any(part.startswith(".") for part in f.relative_to(source).parts):
            continue
        rel = f.relative_to(source)
        title = " ".join(rel.with_suffix("").parts)[:80]
        s = slug(title)
        if s in seen:
            continue
        seen.add(s)
        try:
            body = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        body = body[:20000]                      # cap giants; keep verbatim text
        mem.write_note(title, body, source=str(rel))
        notes.append({"slug": s, "title": title, "chars": len(body)})
    return notes


def gen_queries(vault: Path, notes: list[dict], n: int,
                completer) -> list[dict]:
    """One frozen paraphrase query per sampled note (single LLM call)."""
    if QUERY_FILE.is_file():
        cached = json.loads(QUERY_FILE.read_text(encoding="utf-8"))
        if cached.get("n") == n:
            print(f"reusing frozen query set ({len(cached['queries'])})")
            return cached["queries"]
    import random
    rng = random.Random(42)
    sample = rng.sample(notes, min(n, len(notes)))
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    lines = []
    for m in sample:
        e = dex.entries().get(m["slug"]) or {}
        body = (vault / e.get("rel", m["slug"] + ".md")).read_text(
            encoding="utf-8", errors="replace")
        body = re.sub(r"^---.*?---\s*", "", body, flags=re.S)[:600]
        lines.append(f"- slug: {m['slug']}\n  content: {body!r}")
    raw = completer(QUERY_GEN_PROMPT.format(notes="\n".join(lines)))
    m = re.search(r"\{.*\}", raw, re.S)
    queries = json.loads(m.group(0))["queries"] if m else []
    queries = [q for q in queries if q.get("slug") in {x["slug"] for x in sample}
               and q.get("query")]
    QUERY_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUERY_FILE.write_text(json.dumps({"n": n, "frozen_at": _now(),
                                      "queries": queries},
                                     indent=1, ensure_ascii=False),
                          encoding="utf-8")
    print(f"froze {len(queries)} queries -> {QUERY_FILE}")
    return queries


def measure(vault: Path, queries: list[dict], *, expand: bool) -> dict:
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    ranks: list[int | None] = []
    exp_hits = 0
    for q in queries:
        hits = dex.search(q["query"], limit=10)
        order = [h["slug"] for h in hits]
        rank = order.index(q["slug"]) + 1 if q["slug"] in order else None
        ranks.append(rank)
        if expand:
            # top-3 hits expanded with their wikilink neighbors
            pool = set(order[:3])
            for s in order[:3]:
                e = dex.entries().get(s) or {}
                pool |= {slug(t) for t in e.get("links", [])}
            exp_hits += q["slug"] in pool
    n = len(ranks) or 1
    out = {"n": len(ranks),
           "recall@1": round(sum(r == 1 for r in ranks) / n, 3),
           "recall@5": round(sum(r is not None and r <= 5 for r in ranks) / n, 3),
           "recall@10": round(sum(r is not None for r in ranks) / n, 3),
           "mrr": round(sum(1 / r for r in ranks if r) / n, 3)}
    if expand:
        out["recall_top3+links"] = round(exp_hits / n, 3)
    return out


def graph_stats(vault: Path) -> dict:
    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    entries = dex.entries()
    zones: dict[str, int] = {}
    links = 0
    for e in entries.values():
        z = e.get("zone") or "inbox"
        zones[z] = zones.get(z, 0) + 1
        links += len(e.get("links", []))
    return {"notes": len(entries), "zones": zones,
            "directed_links": links,
            "avg_degree": round(links / max(1, len(entries)), 2)}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--provider", default="claude")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--vault", default=None,
                    help="reuse an existing experiment vault")
    ap.add_argument("--skip-curation", action="store_true")
    args = ap.parse_args()

    import tempfile
    vault = Path(args.vault) if args.vault else \
        Path(tempfile.mkdtemp(prefix="bk-realvault-")) / "vault"
    cfg = config.load_config()
    completer = providers.get_completer(args.provider, model=args.model,
                                        cfg=cfg, cwd=str(vault))

    print(f"vault: {vault}")
    notes = ingest(Path(args.source), vault)
    print(f"ingested {len(notes)} real notes "
          f"({sum(n['chars'] for n in notes)//1000} KB)")

    queries = gen_queries(vault, notes, args.queries, completer)

    print("condition A: raw inbox …")
    before = measure(vault, queries, expand=True)
    g_before = graph_stats(vault)
    print(json.dumps(before, ensure_ascii=False))

    result = {"meta": {"date": _now(), "source": args.source,
                       "notes": len(notes), "queries": len(queries),
                       "curator": f"{args.provider}/{args.model}"},
              "before": {"retrieval": before, "graph": g_before}}

    if not args.skip_curation:
        print("running CurationPlan/1 pass …")
        t0 = time.perf_counter()
        out = curation.run_curation_pass(vault, completer,
                                         provider=args.provider,
                                         model=args.model)
        mins = round((time.perf_counter() - t0) / 60, 1)
        print(f"curation: {out.plan_ops} ops proposed, "
              f"{len(out.accepted)} accepted, {len(out.dropped)} dropped "
              f"({mins} min)")
        print("condition B: after curation …")
        after = measure(vault, queries, expand=True)
        g_after = graph_stats(vault)
        print(json.dumps(after, ensure_ascii=False))
        result["curation"] = {"ops_proposed": out.plan_ops,
                              "accepted": len(out.accepted),
                              "dropped": len(out.dropped),
                              "minutes": mins}
        result["after"] = {"retrieval": after, "graph": g_after}

    RES.mkdir(parents=True, exist_ok=True)
    p = RES / f"realvault-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    p.write_text(json.dumps(result, indent=1, ensure_ascii=False),
                 encoding="utf-8")
    print(f"written: {p}")
    print(f"vault kept for inspection: {vault}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
