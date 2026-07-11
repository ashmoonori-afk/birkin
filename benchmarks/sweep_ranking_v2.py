"""One-load parameter sweep for ranking-v2 (dev split only — never test).

Loads the 277 MB dataset once, precomputes per-question doc structures, then
evaluates a (k1, b, w_user) grid for bm25f. Also dumps a per-question error
manifest for the best config so the next design round is data-driven.

Usage:
  python benchmarks/sweep_ranking_v2.py --data <dir>/longmemeval_s_cleaned.json
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from _lme_common import metrics
from bench_ranking_v2 import build_postings, bm25_weighted, prep_docs, ranked
from birkin.mnemosyne import tokenize

RES = Path("benchmarks/results")
HYBRID_BAR = {"recall@1": 0.894, "recall@5": 0.977, "mrr": 0.931}


def first_hit(order, evidence):
    for i, sid in enumerate(order, 1):
        if sid in evidence:
            return i
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--k1", default="0.9,1.2,1.5,2.0")
    ap.add_argument("--b", default="0.3,0.5,0.75,0.9")
    ap.add_argument("--w-user", default="1.0,1.5,2.0,3.0")
    args = ap.parse_args()
    k1s = [float(x) for x in args.k1.split(",")]
    bs = [float(x) for x in args.b.split(",")]
    wus = [float(x) for x in args.w_user.split(",")]

    print(f"loading {args.data} …", flush=True)
    instances = json.loads(Path(args.data).read_text(encoding="utf-8"))

    # DEV split (even usable-question index), structures precomputed once
    qs = []
    qidx = -1
    for inst in instances:
        qid = str(inst.get("question_id", ""))
        evidence = set(map(str, inst.get("answer_session_ids") or []))
        if qid.endswith("_abs") or not evidence:
            continue
        sids = [str(s) for s in inst.get("haystack_session_ids") or []]
        if not sids or not evidence & set(sids):
            continue
        qidx += 1
        if qidx % 2 == 1:
            continue                                    # dev only
        qs.append({"qid": qid, "q": str(inst.get("question") or ""),
                   "type": str(inst.get("question_type") or "?"),
                   "evidence": evidence,
                   "docs": prep_docs(sids, inst.get("haystack_sessions") or [])})
    print(f"dev questions: {len(qs)}; grid "
          f"{len(k1s)}x{len(bs)}x{len(wus)}", flush=True)

    rows = []
    t0 = time.perf_counter()
    for k1 in k1s:
        for b in bs:
            for wu in wus:
                ranks = []
                for item in qs:
                    postings, doclens, avgdl = build_postings(
                        item["docs"], w_user=wu)
                    qw = {t: 1.0 for t in tokenize(item["q"])}
                    order = ranked(bm25_weighted(
                        qw, postings, doclens, avgdl, len(item["docs"]),
                        k1=k1, b=b), item["docs"])
                    ranks.append(first_hit(order, item["evidence"]))
                m = metrics(ranks)
                rows.append({"k1": k1, "b": b, "w_user": wu, **m})
                print(f"k1={k1:<4} b={b:<4} w_user={wu:<4} "
                      f"R@1 {m['recall@1']:.3f} R@5 {m['recall@5']:.3f} "
                      f"MRR {m['mrr']:.3f}  ({time.perf_counter()-t0:.0f}s)",
                      flush=True)

    rows.sort(key=lambda r: (-r["mrr"], -r["recall@1"]))
    best = rows[0]
    print("\nTOP 5 by MRR (dev):")
    for r in rows[:5]:
        print(f"  k1={r['k1']} b={r['b']} w_user={r['w_user']} "
              f"R@1 {r['recall@1']} R@5 {r['recall@5']} MRR {r['mrr']}")
    print(f"hybrid bar: {HYBRID_BAR}")

    # error manifest for the best config — fuel for the next design round
    errs = []
    for item in qs:
        postings, doclens, avgdl = build_postings(
            item["docs"], w_user=best["w_user"])
        qw = {t: 1.0 for t in tokenize(item["q"])}
        s = bm25_weighted(qw, postings, doclens, avgdl, len(item["docs"]),
                          k1=best["k1"], b=best["b"])
        order = ranked(s, item["docs"])
        r = first_hit(order, item["evidence"])
        if r == 1:
            continue
        ev = next(iter(item["evidence"] & set(order)), None)
        errs.append({
            "qid": item["qid"], "type": item["type"], "rank": r,
            "question": item["q"],
            "top1_len": int(item["docs"][order[0]]["len"]),
            "evidence_len": int(item["docs"][ev]["len"]) if ev else None,
            "q_terms_in_top1": len(set(tokenize(item["q"]))
                                   & set(item["docs"][order[0]]["tf"])),
            "q_terms_in_evidence": len(set(tokenize(item["q"]))
                                       & set(item["docs"][ev]["tf"])) if ev else 0,
        })
    out = {"meta": {"date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "split": "dev", "n": len(qs), "hybrid_bar": HYBRID_BAR},
           "grid": rows, "best": best, "errors_at_best": errs}
    RES.mkdir(parents=True, exist_ok=True)
    p = RES / f"rankingv2-sweep-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False),
                 encoding="utf-8")
    print(f"\nerrors at best config: {len(errs)} "
          f"(by type: { {t: sum(1 for e in errs if e['type']==t) for t in {e['type'] for e in errs}} })")
    print(f"written: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
