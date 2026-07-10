"""Strong dense baselines for LongMemEval-S (review requirement #2).

The prior comparison fed each session's first 6,000 chars to a 512-token
encoder — the weakest reasonable dense setup. This harness gives embeddings
their best practical shot in ONE pass over the dataset, all conditions
sharing the same per-question chunk embeddings:

  bm25            full-text BM25 (reproduces the paper headline)
  dense_trunc     6k-truncated whole-session embedding (prior setup)
  dense_chunk     chunked sessions (1,200 chars, 200 overlap), session score
                  = MAX chunk cosine (late max-pooling — the standard fix for
                  encoder windows)
  rrf_k20/60/120  BM25 + dense_chunk reciprocal-rank fusion, k swept (was a
                  single untuned k=60)
  rerank_top20    BM25 shortlist (top-20) re-ordered by dense_chunk score
                  (BM25 -> dense reranking)

Usage:
  python benchmarks/bench_dense_strong.py --data <dir>/longmemeval_s_cleaned.json
      [--limit 500] [--model BAAI/bge-small-en-v1.5]
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

from _lme_common import session_text, bm25_rank, first_hit, metrics


def chunks_of(text: str, size: int = 1200, overlap: int = 200) -> list[str]:
    out = []
    i = 0
    while i < len(text):
        out.append(text[i:i + size])
        if i + size >= len(text):
            break
        i += size - overlap
    return out or [""]


def rrf(rankings: list[list[str]], k: int) -> list[str]:
    score: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, sid in enumerate(ranking):
            score[sid] += 1.0 / (k + rank + 1)
    return sorted(score, key=lambda s: score[s], reverse=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--model", default="BAAI/bge-small-en-v1.5")
    ap.add_argument("--out", default="benchmarks/results")
    args = ap.parse_args()

    from fastembed import TextEmbedding
    print(f"loading {args.model} …")
    embedder = TextEmbedding(model_name=args.model)
    e5 = "e5" in args.model.lower()

    instances = json.loads(Path(args.data).read_text(encoding="utf-8"))
    conds = ["bm25", "dense_trunc", "dense_chunk",
             "rrf_k20", "rrf_k60", "rrf_k120", "rerank_top20"]
    ranks: dict[str, list] = {c: [] for c in conds}
    used = 0
    t0 = time.perf_counter()

    for inst in instances:
        if used >= args.limit:
            break
        qid = str(inst.get("question_id", ""))
        evidence = set(map(str, inst.get("answer_session_ids") or []))
        if qid.endswith("_abs") or not evidence:
            continue
        sids = [str(s) for s in inst.get("haystack_session_ids") or []]
        docs = {sid: session_text(s) for sid, s in
                zip(sids, inst.get("haystack_sessions") or [])}
        if not docs or not evidence & set(docs):
            continue
        q = str(inst.get("question") or "")
        ids = list(docs)

        # one embedding pass: query + truncated sessions + all chunks
        chunk_lists = {s: chunks_of(docs[s]) for s in ids}
        texts = [f"query: {q}" if e5 else q]
        texts += [(f"passage: {docs[s][:6000]}" if e5 else docs[s][:6000])
                  for s in ids]
        flat_chunks: list[tuple[str, int]] = []
        for s in ids:
            for c in chunk_lists[s]:
                flat_chunks.append((s, len(texts)))
                texts.append(f"passage: {c}" if e5 else c)
        vecs = np.array(list(embedder.embed(texts)), dtype=np.float32)
        vecs /= (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)
        qv = vecs[0]
        trunc_sims = {s: float(vecs[1 + i] @ qv) for i, s in enumerate(ids)}
        chunk_best: dict[str, float] = {s: -1.0 for s in ids}
        for s, vi in flat_chunks:
            sim = float(vecs[vi] @ qv)
            if sim > chunk_best[s]:
                chunk_best[s] = sim

        r_bm = bm25_rank(q, docs)
        r_tr = sorted(ids, key=lambda s: -trunc_sims[s])
        r_ch = sorted(ids, key=lambda s: -chunk_best[s])
        ranks["bm25"].append(first_hit(r_bm, evidence))
        ranks["dense_trunc"].append(first_hit(r_tr, evidence))
        ranks["dense_chunk"].append(first_hit(r_ch, evidence))
        for k in (20, 60, 120):
            ranks[f"rrf_k{k}"].append(first_hit(rrf([r_bm, r_ch], k), evidence))
        short = r_bm[:20]
        rr = sorted(short, key=lambda s: -chunk_best[s]) + r_bm[20:]
        ranks["rerank_top20"].append(first_hit(rr, evidence))

        used += 1
        if used % 25 == 0:
            print(f"  {used} done ({time.perf_counter()-t0:.0f}s)", flush=True)

    result = {"meta": {"date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                       "model": args.model, "questions": used,
                       "chunk": {"size": 1200, "overlap": 200,
                                 "pool": "max"},
                       "minutes": round((time.perf_counter() - t0) / 60, 1)}}
    for c in conds:
        result[c] = metrics(ranks[c])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"dense-strong-{datetime.now().strftime('%Y%m%d')}.json"
    p.write_text(json.dumps(result, indent=1), encoding="utf-8")
    for c in conds:
        m = result[c]
        print(f"{c:13} R@1 {m['recall@1']:.3f}  R@5 {m['recall@5']:.3f}  "
              f"MRR {m['mrr']:.3f}")
    print(f"written: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
