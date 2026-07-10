"""Link-policy analysis on the real-vault experiment (review §8).

The executor densely links co-placed notes; the review warns this risks
O(n^2) link growth, an uninformative graph, and amplified errors in
linked-neighbor retrieval. This script answers, WITHOUT re-running any LLM:

  1. What did dense linking actually produce on the real 1,910-note vault?
     (graph density, degree distribution, per-zone concentration)
  2. Would a cheaper policy — keep only each note's top-k lexically most
     similar linked neighbors, or a similarity threshold — retain the
     link-expansion retrieval benefit while cutting the graph?

Read-only: loads the kept post-curation vault + the frozen query set, prunes
the link graph in memory per policy, and re-scores the same link-expansion
retrieval measure used by bench_real_vault.py (recall_top3+links).

Usage:
  python benchmarks/link_policy_analysis.py
      [--vault C:/Users/lg/AppData/Local/Temp/bk-realvault-v_l2qem9/vault]
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from statistics import median

from birkin import mnemosyne
from birkin.mnemosyne import slug, tokenize

RES = Path("benchmarks/results")
QUERY_FILE = RES / "realvault-queries.json"
DEFAULT_VAULT = r"C:\Users\lg\AppData\Local\Temp\bk-realvault-v_l2qem9\vault"
BODY_CAP = 2000  # chars of note body used for similarity


def load_graph(dex: mnemosyne.Mnemosyne) -> tuple[dict, dict[str, set[str]]]:
    """entries + directed adjacency (slug -> set of linked slugs)."""
    entries = dex.entries()
    adj = {s: {slug(t) for t in e.get("links", [])} & entries.keys() - {s}
           for s, e in entries.items()}
    return entries, adj


def note_tokens(vault: Path, entries: dict, cache: dict) -> dict[str, set[str]]:
    """Token set per note (title + capped body), computed once."""
    if cache:
        return cache
    for s, e in entries.items():
        try:
            body = (vault / e.get("rel", s + ".md")).read_text(
                encoding="utf-8", errors="replace")[:BODY_CAP]
        except OSError:
            body = ""
        cache[s] = set(tokenize(e.get("title", "") + " " + body))
    return cache


def sim(a: set[str], b: set[str]) -> float:
    """Cosine over token sets — deterministic, stdlib, matches the paper's
    lexical philosophy."""
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


def graph_stats(entries: dict, adj: dict[str, set[str]]) -> dict:
    degs = [len(v) for v in adj.values()]
    links = sum(degs)
    # per-zone: how close each zone's internal graph is to complete (O(n^2))
    zones: dict[str, list[str]] = {}
    for s, e in entries.items():
        zones.setdefault(e.get("zone") or "inbox", []).append(s)
    zone_rows = []
    for z, members in zones.items():
        n = len(members)
        mset = set(members)
        internal = sum(len(adj[s] & mset) for s in members)
        possible = n * (n - 1)
        zone_rows.append({"zone": z, "notes": n, "internal_links": internal,
                          "density": round(internal / possible, 3) if possible else 0.0})
    zone_rows.sort(key=lambda r: -r["internal_links"])
    return {"directed_links": links,
            "avg_degree": round(links / max(1, len(entries)), 2),
            "median_degree": median(degs) if degs else 0,
            "p95_degree": sorted(degs)[int(0.95 * (len(degs) - 1))] if degs else 0,
            "max_degree": max(degs) if degs else 0,
            "zones": len(zones),
            "worst_zones": zone_rows[:5]}


def prune_topk(adj: dict[str, set[str]], toks: dict[str, set[str]],
               k: int) -> dict[str, set[str]]:
    return {u: set(sorted(vs, key=lambda v: -sim(toks[u], toks[v]))[:k])
            for u, vs in adj.items()}


def prune_threshold(adj: dict[str, set[str]], toks: dict[str, set[str]],
                    tau: float) -> dict[str, set[str]]:
    return {u: {v for v in vs if sim(toks[u], toks[v]) >= tau}
            for u, vs in adj.items()}


def expansion_recall(dex: mnemosyne.Mnemosyne, queries: list[dict],
                     adj: dict[str, set[str]]) -> float:
    """recall_top3+links from bench_real_vault.measure, with a swappable
    link graph: top-3 hits expanded with their (policy-pruned) neighbors."""
    hits_n = 0
    for q in queries:
        order = [h["slug"] for h in dex.search(q["query"], limit=10)]
        pool = set(order[:3])
        for s in order[:3]:
            pool |= adj.get(s, set())
        hits_n += q["slug"] in pool
    return round(hits_n / max(1, len(queries)), 3)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=DEFAULT_VAULT)
    args = ap.parse_args()
    vault = Path(args.vault)
    if not vault.is_dir():
        raise SystemExit(f"vault not found: {vault}")
    queries = json.loads(QUERY_FILE.read_text(encoding="utf-8"))["queries"]

    dex = mnemosyne.Mnemosyne(vault)
    dex.refresh()
    entries, dense = load_graph(dex)
    toks = note_tokens(vault, entries, {})

    # threshold tau = median similarity of existing links (data-derived, not tuned)
    link_sims = [sim(toks[u], toks[v]) for u, vs in dense.items() for v in vs]
    tau = round(median(link_sims), 3) if link_sims else 0.0

    policies: dict[str, dict[str, set[str]]] = {
        "dense (current)": dense,
        "topk_3": prune_topk(dense, toks, 3),
        "topk_5": prune_topk(dense, toks, 5),
        "topk_10": prune_topk(dense, toks, 10),
        f"threshold_{tau}": prune_threshold(dense, toks, tau),
    }

    out = {"meta": {"date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "vault_notes": len(entries), "queries": len(queries),
                    "link_sim_median": tau},
           "policies": {}}
    print(f"{'policy':<18} {'links':>6} {'avg':>5} {'p95':>4} {'max':>4} "
          f"{'R_top3+links':>12}")
    for name, adj in policies.items():
        g = graph_stats(entries, adj)
        r = expansion_recall(dex, queries, adj)
        out["policies"][name] = {**g, "recall_top3+links": r}
        print(f"{name:<18} {g['directed_links']:>6} {g['avg_degree']:>5} "
              f"{g['p95_degree']:>4} {g['max_degree']:>4} {r:>12}")

    RES.mkdir(parents=True, exist_ok=True)
    p = RES / f"linkpolicy-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"written: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
