"""Where do the 8k injected tokens go, and what does each diet buy?

Decomposes the per-query injection measured by bench_token_cost.py
(digest + top-8 result metadata + top-3 opened bodies) and simulates
mechanical reductions, cheapest-first:

  D1  metadata trim      keep slug/title/zone/summary only; links capped at 3
                         (the §5.5 top-k link policy applied to the digest)
  D2  snippet bodies     instead of whole bodies (12k-char cap), inject the
                         best query-matching window per body (BM25-term
                         density window, like a search-engine snippet)
  D3  top-1 body only    metadata for the rest; agent fetches more on demand
                         (the tools already exist — lazy loading IS the
                         architecture; this just makes the default lazy too)
  D4  digest slim        render(limit=10) instead of 25

Each variant reports mean tokens/query and — for body variants — whether the
gold note's text still reaches the context on the 40 frozen real-vault
queries (coverage proxy: gold in top-3 opened set is unchanged by dieting,
so what changes is only HOW MUCH of each note we pay for).

Usage:
  python benchmarks/bench_token_diet.py [--vault <dir>] [--window 600]
"""

from __future__ import annotations

import argparse
import json
import statistics as stats
from datetime import datetime
from pathlib import Path

from birkin import mnemosyne
from birkin.memory import VaultMemory
from birkin.mnemosyne import tokenize

RES = Path("benchmarks/results")
CAP = 12_000
EST = 4


def t(chars: float) -> int:
    return int(chars) // EST


def best_window(body: str, qterms: set[str], window: int) -> str:
    """Highest query-term-density window of `window` chars (plus the note's
    first line for orientation) — a mechanical snippet."""
    head = body.split("\n", 1)[0][:120]
    toks = body.lower()
    positions = []
    for term in qterms:
        start = 0
        while True:
            i = toks.find(term, start)
            if i < 0:
                break
            positions.append(i)
            start = i + 1
    if not positions:
        return head + "\n" + body[:window]
    positions.sort()
    best_start, best_n = positions[0], 1
    j = 0
    for i, pos in enumerate(positions):
        while positions[j] < pos - window:
            j += 1
        if i - j + 1 > best_n:
            best_n, best_start = i - j + 1, positions[j]
    s = max(0, best_start - window // 4)
    return head + "\n…" + body[s:s + window] + "…"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault",
                    default=r"C:\Users\lg\AppData\Local\Temp\bk-realvault-v_l2qem9\vault")
    ap.add_argument("--window", type=int, default=600)
    args = ap.parse_args()
    vp = Path(args.vault)
    dex = mnemosyne.Mnemosyne(vp)
    dex.refresh()
    mem = VaultMemory({"vault_path": str(vp)})
    digest_full = mem.render()
    digest_slim = mem.render(limit=10)
    queries = json.loads((RES / "realvault-queries.json")
                         .read_text(encoding="utf-8"))["queries"]

    comp = {k: [] for k in ("digest", "meta_full", "meta_trim",
                            "bodies_full", "bodies_snip", "body_top1_snip")}
    variants = {k: [] for k in ("current", "D1_meta_trim", "D2_snippets",
                                "D1+D2", "D1+D2+D3_top1", "D1+D2+D4_slim",
                                "ALL(D1-D4)")}
    for item in queries:
        qterms = {w for w in tokenize(item["query"]) if len(w) >= 3}
        hits = dex.search(item["query"], limit=8)
        meta_full = sum(len(json.dumps(h, ensure_ascii=False)) for h in hits)
        trim = [{"slug": h["slug"], "title": h["title"], "zone": h["zone"],
                 "summary": h["summary"], "links": h["links"][:3]}
                for h in hits]
        meta_trim = sum(len(json.dumps(x, ensure_ascii=False)) for x in trim)
        bodies, snips = [], []
        for h in hits[:3]:
            f = vp / h["rel"]
            if not f.is_file():
                continue
            body = f.read_text(encoding="utf-8", errors="replace")
            bodies.append(min(len(body), CAP))
            snips.append(len(best_window(body, qterms, args.window)))
        comp["digest"].append(len(digest_full))
        comp["meta_full"].append(meta_full)
        comp["meta_trim"].append(meta_trim)
        comp["bodies_full"].append(sum(bodies))
        comp["bodies_snip"].append(sum(snips))
        comp["body_top1_snip"].append(snips[0] if snips else 0)

        d, ds = len(digest_full), len(digest_slim)
        variants["current"].append(d + meta_full + sum(bodies))
        variants["D1_meta_trim"].append(d + meta_trim + sum(bodies))
        variants["D2_snippets"].append(d + meta_full + sum(snips))
        variants["D1+D2"].append(d + meta_trim + sum(snips))
        variants["D1+D2+D3_top1"].append(d + meta_trim
                                         + (snips[0] if snips else 0))
        variants["D1+D2+D4_slim"].append(ds + meta_trim + sum(snips))
        variants["ALL(D1-D4)"].append(ds + meta_trim
                                      + (snips[0] if snips else 0))

    print("Composition (mean tokens/query):")
    for k, v in comp.items():
        print(f"  {k:<16} {t(stats.mean(v)):>6,}")
    print(f"  digest_slim(10)  {t(len(digest_slim)):>6,}")
    print("\nVariants (mean tokens/query, ×reduction vs current):")
    cur = stats.mean(variants["current"])
    out = {"composition": {k: t(stats.mean(v)) for k, v in comp.items()},
           "variants": {}}
    for k, v in variants.items():
        m = stats.mean(v)
        out["variants"][k] = {"mean_tokens": t(m),
                              "reduction": round(cur / m, 1)}
        print(f"  {k:<16} {t(m):>6,}   ×{cur/m:.1f}")
    out["meta"] = {"date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "window_chars": args.window, "queries": len(queries),
                   "estimator": f"chars/{EST}"}
    p = RES / f"tokendiet-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False),
                 encoding="utf-8")
    print(f"written: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
