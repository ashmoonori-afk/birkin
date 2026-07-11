"""Ranking-v2 round 5: word-bigram phrase field on top of the round-4 frozen
config (bm25f w_user=3, k1=0.9, b=0.5, query idf^1, time prior lam=0.3).

Rationale: after idf emphasis, remaining top-1 errors are aboutness confusions
where the wrong session covers MORE query unigrams. Consecutive-word phrases
("chocolate chip", "smart thermostat") are the orthogonal lexical signal BM25
unigrams ignore. Score = unigram_score + W_BI * bigram_score, both idf^1.

DEV sweeps W_BI; test gets ONE evaluation of the winner. Test evaluations of
this experiment line so far: 1 (round 4). This will be #2 — reported honestly.

Usage:
  python benchmarks/sweep3_ranking_v2.py --data <...>.json [--split dev|test|full]
"""

from __future__ import annotations

import argparse
import json
import math
import time as _time
from datetime import datetime
from pathlib import Path

from _lme_common import metrics
from bench_ranking_v2 import build_postings, bm25_weighted, prep_docs, ranked
from birkin.mnemosyne import tokenize
from sweep2_ranking_v2 import (HYBRID_BAR, K1_, B_, WU_, apply_time_prior,
                               parse_dt, temporal_target)

RES = Path("benchmarks/results")
W_BI_FINAL = 0.5          # frozen after the dev sweep below (see results file)


def bigrams(toks: list[str]) -> list[str]:
    return [toks[i] + "␣" + toks[i + 1] for i in range(len(toks) - 1)]


def build_bigram_postings(docs: dict) -> tuple[dict, dict, float]:
    postings: dict[str, dict[str, float]] = {}
    doclens: dict[str, float] = {}
    for sid, d in docs.items():
        tf: dict[str, float] = {}
        for g in bigrams(d["toks"]):
            tf[g] = tf.get(g, 0.0) + 1.0
        doclens[sid] = sum(tf.values())
        for g, f in tf.items():
            postings.setdefault(g, {})[sid] = f
    avgdl = (sum(doclens.values()) / len(doclens)) if doclens else 1.0
    return postings, doclens, avgdl


def first_hit(order, evidence):
    for i, sid in enumerate(order, 1):
        if sid in evidence:
            return i
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--split", default="dev", choices=["dev", "test", "full"])
    args = ap.parse_args()

    print(f"loading {args.data} …", flush=True)
    instances = json.loads(Path(args.data).read_text(encoding="utf-8"))
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
        if args.split == "dev" and qidx % 2 == 1:
            continue
        if args.split == "test" and qidx % 2 == 0:
            continue
        qs.append({"qid": qid, "q": str(inst.get("question") or ""),
                   "evidence": evidence,
                   "qdate": parse_dt(str(inst.get("question_date") or "")),
                   "dates": {sid: parse_dt(x) for sid, x in
                             zip(sids, inst.get("haystack_dates") or [])},
                   "docs": prep_docs(sids, inst.get("haystack_sessions") or [])})
    print(f"{args.split} questions: {len(qs)}", flush=True)

    t0 = _time.perf_counter()
    for item in qs:
        item["ppda"] = build_postings(item["docs"], w_user=WU_)
        item["bi"] = build_bigram_postings(item["docs"])
        item["qtoks"] = tokenize(item["q"])
        item["qbi"] = bigrams(item["qtoks"])
    print(f"precompute {_time.perf_counter()-t0:.0f}s", flush=True)

    def idf_weights(terms: list[str], postings: dict, n: int) -> dict[str, float]:
        qw = {}
        for t in set(terms):
            df = len(postings.get(t, {}))
            qw[t] = math.log(1 + (n - df + 0.5) / (df + 0.5))   # idf^1 weight
        return qw

    def scores(item, w_bi: float) -> dict[str, float]:
        n = len(item["docs"])
        p, dl, av = item["ppda"]
        s = bm25_weighted(idf_weights(item["qtoks"], p, n), p, dl, av, n,
                          k1=K1_, b=B_)
        if w_bi:
            bp, bdl, bav = item["bi"]
            sb = bm25_weighted(idf_weights(item["qbi"], bp, n), bp, bdl, bav,
                               n, k1=K1_, b=B_)
            for sid, v in sb.items():
                s[sid] = s.get(sid, 0.0) + w_bi * v
        tgt = temporal_target(item["q"], item["qdate"])
        if tgt:
            s = apply_time_prior(s, item["dates"], tgt[0], tgt[1], 0.3)
        return s

    conds = {}

    def run(name, w_bi):
        ranks = [first_hit(ranked(scores(it, w_bi), it["docs"]), it["evidence"])
                 for it in qs]
        conds[name] = metrics(ranks)
        m = conds[name]
        print(f"{name:<18} R@1 {m['recall@1']:.3f} R@5 {m['recall@5']:.3f} "
              f"R@10 {m['recall@10']:.3f} MRR {m['mrr']:.3f}", flush=True)

    if args.split == "dev":
        for w in (0.0, 0.25, 0.5, 1.0, 2.0):
            run(f"w_bi={w}", w)
    else:
        run("round4(w_bi=0)", 0.0)
        run(f"FINAL2(w_bi={W_BI_FINAL})", W_BI_FINAL)

    out = {"meta": {"date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "split": args.split, "n": len(qs),
                    "params": {"k1": K1_, "b": B_, "w_user": WU_,
                               "idf_p": 1.0, "time_lam": 0.3},
                    "hybrid_bar": HYBRID_BAR},
           "conditions": conds}
    RES.mkdir(parents=True, exist_ok=True)
    p = RES / (f"rankingv2-sweep3-{args.split}-"
               f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
    p.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"hybrid bar: {HYBRID_BAR}")
    print(f"written: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
