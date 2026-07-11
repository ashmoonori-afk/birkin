"""Ranking-v2 harness: can LEXICAL-ONLY beat the embedding hybrid?

Bar to beat (dense-strong-20260711.json, full 470 questions):
    RRF k=20 (BM25 + chunked bge-small):  R@1 0.894  R@5 0.977  MRR 0.931

Conditions here are pure arithmetic — no encoder, no vectors, no model:
    bm25        baseline replication (validates harness against published
                0.870 / 0.968 / 0.910)
    bm25f       BM25F-style field weighting: user-turn tokens get tf x W_USER
                (queries ask about the *user*, so their turns carry the anchors)
    prox        bm25 + span-proximity bonus on the top-POOL candidates
                (Tao & Zhai 2007 flavor: reward query terms co-occurring close)
    rm3         guarded pseudo-relevance feedback (Abdul-Jaleel 2004): expand
                the query with top terms from top-3 hits unless the ranker is
                already confident
    fuse        RRF fusion of the lexical rankers above — a "hybrid" with no
                embedding in it

Anti-overfit protocol (the review's lesson): even-index questions = DEV
(sweeps allowed), odd-index = TEST (frozen; run once per finalized config).
Full-set numbers are reported for the finalized config only.

Usage:
  python benchmarks/bench_ranking_v2.py --data <dir>/longmemeval_s_cleaned.json
      [--split dev|test|full] [--limit 500] [--w-user 2.0] [--prox-alpha 0.5]
      [--prox-window 24] [--rm3-terms 8] [--rm3-weight 0.3] [--pool 50]
      [--conditions bm25,bm25f,prox,rm3,fuse]
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from birkin.mnemosyne import K1, B, tokenize
from _lme_common import metrics

RES = Path("benchmarks/results")
HYBRID_BAR = {"recall@1": 0.894, "recall@5": 0.977, "mrr": 0.931}


# ---------------------------------------------------------------- corpus prep

def prep_docs(sids: list[str], sessions: list[list[dict]]) -> dict[str, dict]:
    """Per-session token structures, computed once per question."""
    docs: dict[str, dict] = {}
    for sid, sess in zip(sids, sessions):
        toks: list[str] = []           # full token stream (positions matter)
        user_tf: dict[str, float] = {}
        for turn in sess:
            if not isinstance(turn, dict):
                continue
            content = str(turn.get("content") or "")
            ttoks = tokenize(content)
            toks.extend(ttoks)
            if str(turn.get("role") or "") == "user":
                for t in ttoks:
                    user_tf[t] = user_tf.get(t, 0.0) + 1.0
        tf: dict[str, float] = {}
        for t in toks:
            tf[t] = tf.get(t, 0.0) + 1.0
        docs[sid] = {"tf": tf, "user_tf": user_tf, "toks": toks,
                     "len": float(len(toks))}
    return docs


def build_postings(docs: dict[str, dict], w_user: float = 1.0
                   ) -> tuple[dict, dict, float]:
    """Inverted index with optional user-turn field weight (BM25F: weighted
    tf folded into one saturation). w_user=1.0 -> plain BM25."""
    postings: dict[str, dict[str, float]] = {}
    doclens: dict[str, float] = {}
    for sid, d in docs.items():
        extra = w_user - 1.0
        dl = d["len"] + extra * sum(d["user_tf"].values())
        doclens[sid] = dl
        for t, f in d["tf"].items():
            wtf = f + extra * d["user_tf"].get(t, 0.0)
            postings.setdefault(t, {})[sid] = wtf
    avgdl = (sum(doclens.values()) / len(doclens)) if doclens else 1.0
    return postings, doclens, avgdl


def bm25_weighted(qw: dict[str, float], postings: dict, doclens: dict,
                  avgdl: float, n_docs: int,
                  k1: float = K1, b: float = B) -> dict[str, float]:
    """Okapi BM25 with per-query-term weights (mnemosyne semantics, plus qw)."""
    scores: dict[str, float] = {}
    avgdl = avgdl or 1.0
    for t, w in qw.items():
        post = postings.get(t)
        if not post:
            continue
        df = len(post)
        idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
        for s, tf in post.items():
            dl = doclens.get(s, avgdl)
            denom = tf + k1 * (1 - b + b * dl / avgdl)
            scores[s] = scores.get(s, 0.0) + w * idf * tf * (k1 + 1) / denom
    return scores


def ranked(scores: dict[str, float], universe: dict) -> list[str]:
    return sorted(universe, key=lambda s: scores.get(s, 0.0), reverse=True)


# ---------------------------------------------------------------- conditions

def cond_bm25(q: str, docs: dict) -> list[str]:
    postings, doclens, avgdl = build_postings(docs)
    qw = {t: 1.0 for t in tokenize(q)}
    return ranked(bm25_weighted(qw, postings, doclens, avgdl, len(docs)), docs)


def cond_bm25f(q: str, docs: dict, w_user: float,
               k1: float = K1, b: float = B) -> list[str]:
    postings, doclens, avgdl = build_postings(docs, w_user=w_user)
    qw = {t: 1.0 for t in tokenize(q)}
    return ranked(bm25_weighted(qw, postings, doclens, avgdl, len(docs),
                                k1=k1, b=b), docs)


def span_bonus(qterms: set[str], toks: list[str], window: int) -> float:
    """Best window of `window` tokens: (#distinct query terms present)^2 /
    window — a cheap span score in the Tao & Zhai spirit."""
    hits = [(i, t) for i, t in enumerate(toks) if t in qterms]
    if len(hits) < 2:
        return 0.0
    best = 0.0
    j = 0
    from collections import Counter
    inwin: Counter = Counter()
    for i, (pos, t) in enumerate(hits):
        inwin[t] += 1
        while hits[j][0] < pos - window:
            inwin[hits[j][1]] -= 1
            if not inwin[hits[j][1]]:
                del inwin[hits[j][1]]
            j += 1
        distinct = len(inwin)
        if distinct >= 2:
            best = max(best, distinct * distinct / window)
    return best


def cond_prox(q: str, docs: dict, base: list[str], alpha: float,
              window: int, pool: int) -> list[str]:
    """Rescore the top-`pool` of a base ranking with a proximity bonus."""
    qterms = set(tokenize(q))
    postings, doclens, avgdl = build_postings(docs)
    qw = {t: 1.0 for t in qterms}
    s = bm25_weighted(qw, postings, doclens, avgdl, len(docs))
    top = max((s.get(x, 0.0) for x in base[:1]), default=1.0) or 1.0
    resc = {}
    for sid in base[:pool]:
        resc[sid] = s.get(sid, 0.0) / top + alpha * span_bonus(
            qterms, docs[sid]["toks"], window)
    rest = base[pool:]
    return sorted(resc, key=lambda x: resc[x], reverse=True) + rest


def cond_rm3(q: str, docs: dict, base: list[str], n_terms: int,
             weight: float, guard: float) -> list[str]:
    """Guarded RM3-lite: skip expansion when the ranker is already confident
    (top-1 score dominates top-2 by `guard` ratio)."""
    postings, doclens, avgdl = build_postings(docs)
    qtoks = tokenize(q)
    qw = {t: 1.0 for t in qtoks}
    s = bm25_weighted(qw, postings, doclens, avgdl, len(docs))
    order = ranked(s, docs)
    if len(order) >= 2:
        s1, s2 = s.get(order[0], 0.0), s.get(order[1], 0.0)
        if s1 > 0 and (s1 - s2) / s1 > guard:
            return order                       # confident — don't touch it
    n_docs = len(docs)
    cand: dict[str, float] = {}
    for sid in order[:3]:
        for t, f in docs[sid]["tf"].items():
            if t in qw or len(t) < 3:
                continue
            df = len(postings.get(t, {}))
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            cand[t] = cand.get(t, 0.0) + f * idf
    for t in sorted(cand, key=lambda x: -cand[x])[:n_terms]:
        qw[t] = weight
    return ranked(bm25_weighted(qw, postings, doclens, avgdl, n_docs), docs)


def cond_bm25_chunk(q: str, docs: dict, chunk_tokens: int = 300,
                    overlap: int = 50, pool: str = "max") -> list[str]:
    """Late max-pooling for LEXICAL retrieval — the same fix that rescued the
    dense baseline (dense_chunk 0.770->0.855): score fixed-size token windows
    with BM25 over the chunk corpus, session score = max (or top2-sum) of its
    chunks. Long diffuse sessions stop beating short precise ones."""
    chunks: dict[str, tuple[str, dict[str, float]]] = {}   # cid -> (sid, tf)
    for sid, d in docs.items():
        toks = d["toks"]
        step = max(1, chunk_tokens - overlap)
        starts = range(0, max(1, len(toks) - overlap), step)
        for ci, st in enumerate(starts):
            w = toks[st:st + chunk_tokens]
            if not w:
                continue
            tf: dict[str, float] = {}
            for t in w:
                tf[t] = tf.get(t, 0.0) + 1.0
            chunks[f"{sid}#{ci}"] = (sid, tf)
    postings: dict[str, dict[str, float]] = {}
    doclens: dict[str, float] = {}
    for cid, (_sid, tf) in chunks.items():
        doclens[cid] = sum(tf.values())
        for t, f in tf.items():
            postings.setdefault(t, {})[cid] = f
    avgdl = (sum(doclens.values()) / len(doclens)) if doclens else 1.0
    qw = {t: 1.0 for t in tokenize(q)}
    cs = bm25_weighted(qw, postings, doclens, avgdl, len(chunks))
    per_sess: dict[str, list[float]] = {sid: [] for sid in docs}
    for cid, sc in cs.items():
        per_sess[chunks[cid][0]].append(sc)
    agg = {}
    for sid, lst in per_sess.items():
        lst.sort(reverse=True)
        agg[sid] = (lst[0] if lst else 0.0) if pool == "max" else \
            sum(lst[:2]) if lst else 0.0
    return sorted(docs, key=lambda s: agg.get(s, 0.0), reverse=True)


def cond_fuse(rankings: list[list[str]], k: int = 60) -> list[str]:
    sc: dict[str, float] = {}
    for r in rankings:
        for i, sid in enumerate(r):
            sc[sid] = sc.get(sid, 0.0) + 1.0 / (k + i + 1)
    return sorted(sc, key=lambda x: -sc[x])


# ---------------------------------------------------------------- evaluation

def first_hit(order: list[str], evidence: set) -> int | None:
    for i, sid in enumerate(order, 1):
        if sid in evidence:
            return i
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--split", default="dev", choices=["dev", "test", "full"])
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--w-user", type=float, default=2.0)
    ap.add_argument("--prox-alpha", type=float, default=0.5)
    ap.add_argument("--prox-window", type=int, default=24)
    ap.add_argument("--pool", type=int, default=50)
    ap.add_argument("--rm3-terms", type=int, default=8)
    ap.add_argument("--rm3-weight", type=float, default=0.3)
    ap.add_argument("--rm3-guard", type=float, default=0.5)
    ap.add_argument("--fuse-k", type=int, default=60)
    ap.add_argument("--chunk-tokens", type=int, default=300)
    ap.add_argument("--chunk-overlap", type=int, default=50)
    ap.add_argument("--chunk-pool", default="max", choices=["max", "top2"])
    ap.add_argument("--conditions", default="bm25,bm25f,prox,rm3,fuse")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    conds = [c.strip() for c in args.conditions.split(",") if c.strip()]
    print(f"loading {args.data} …", flush=True)
    instances = json.loads(Path(args.data).read_text(encoding="utf-8"))
    ranks: dict[str, list] = defaultdict(list)
    used = 0
    qidx = -1
    t0 = time.perf_counter()
    for inst in instances:
        qid = str(inst.get("question_id", ""))
        evidence = set(map(str, inst.get("answer_session_ids") or []))
        if qid.endswith("_abs") or not evidence:
            continue
        sids = [str(s) for s in inst.get("haystack_session_ids") or []]
        sessions = inst.get("haystack_sessions") or []
        docs_txt_ok = bool(sids) and bool(evidence & set(sids))
        if not docs_txt_ok:
            continue
        qidx += 1                       # index over USABLE questions only
        if args.split == "dev" and qidx % 2 == 1:
            continue
        if args.split == "test" and qidx % 2 == 0:
            continue
        if used >= args.limit:
            break
        used += 1
        q = str(inst.get("question") or "")
        docs = prep_docs(sids, sessions)

        order_bm25 = cond_bm25(q, docs)
        produced: dict[str, list[str]] = {"bm25": order_bm25}
        if "bm25f" in conds or "fuse" in conds:
            produced["bm25f"] = cond_bm25f(q, docs, args.w_user)
        if "prox" in conds or "fuse" in conds:
            produced["prox"] = cond_prox(q, docs, order_bm25,
                                         args.prox_alpha, args.prox_window,
                                         args.pool)
        if "rm3" in conds or "fuse" in conds:
            produced["rm3"] = cond_rm3(q, docs, order_bm25, args.rm3_terms,
                                       args.rm3_weight, args.rm3_guard)
        if {"chunk", "fuse2", "fuse3"} & set(conds):
            produced["chunk"] = cond_bm25_chunk(
                q, docs, args.chunk_tokens, args.chunk_overlap, args.chunk_pool)
        if "fuse" in conds:
            produced["fuse"] = cond_fuse(
                [produced["bm25f"], produced["prox"], produced["rm3"]],
                k=args.fuse_k)
        if "fuse2" in conds:   # all-lexical analogue of BM25+dense_chunk RRF
            produced["fuse2"] = cond_fuse(
                [produced["bm25"], produced["chunk"]], k=args.fuse_k)
        if "fuse3" in conds:
            produced["fuse3"] = cond_fuse(
                [produced.get("bm25f") or cond_bm25f(q, docs, args.w_user),
                 produced["chunk"], produced["bm25"]], k=args.fuse_k)
        for name in conds:
            ranks[name].append(first_hit(produced[name], evidence))
        if used % 50 == 0:
            print(f"  {used} done ({time.perf_counter()-t0:.0f}s)", flush=True)

    out = {"meta": {"date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "split": args.split, "questions": used,
                    "params": {k: v for k, v in vars(args).items()
                               if k not in ("data", "conditions", "tag")},
                    "hybrid_bar": HYBRID_BAR},
           "conditions": {name: metrics(r) for name, r in ranks.items()}}
    print(f"\nsplit={args.split} n={used}  "
          f"(hybrid bar: R@1 {HYBRID_BAR['recall@1']} "
          f"R@5 {HYBRID_BAR['recall@5']} MRR {HYBRID_BAR['mrr']})")
    print(f"{'condition':<10} {'R@1':>6} {'R@5':>6} {'R@10':>6} {'MRR':>6}")
    for name, m in out["conditions"].items():
        print(f"{name:<10} {m['recall@1']:>6} {m['recall@5']:>6} "
              f"{m['recall@10']:>6} {m['mrr']:>6}")
    RES.mkdir(parents=True, exist_ok=True)
    tag = (args.tag + "-") if args.tag else ""
    p = RES / (f"rankingv2-{tag}{args.split}-"
               f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
    p.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"written: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
