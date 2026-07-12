"""Does snippet injection preserve ANSWER quality? (token-diet D2, e2e check)

The diet numbers show snippets cut the dominant context cost ~10x; this
verifies the other side: a reader answering from 600-char best-window
snippets vs full sessions (12k-char cap), same top-3 tuned-lexical ranking,
same reader/judge protocol as the paper's e2e study (haiku reader, sonnet
judge). DEV-half sample only (test half stays frozen for ranking work).

Usage:
  python benchmarks/bench_snippet_e2e.py --data <dir>/longmemeval_s_cleaned.json
      [--n 60] [--reader haiku] [--judge sonnet]
"""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime
from pathlib import Path

import lme_e2e_support as support
from bench_lme_e2e import JUDGE_PROMPT, READER_PROMPT, is_abstention
from bench_ranking_v2 import build_postings, bm25_weighted, prep_docs, ranked
from bench_token_diet import best_window
from sweep2_ranking_v2 import (K1_, B_, WU_, apply_time_prior, parse_dt,
                               temporal_target)
from _lme_common import session_text
from birkin import config
from birkin.mnemosyne import tokenize

RES = Path("benchmarks/results")
CAP = 12_000
SNIP = 600
EST = 4


def tuned_order(inst: dict, docs: dict) -> list[str]:
    q = str(inst.get("question") or "")
    p, dl, av = build_postings(docs, w_user=WU_)
    qw = {}
    for t in set(tokenize(q)):
        df = len(p.get(t, {}))
        qw[t] = math.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
    s = bm25_weighted(qw, p, dl, av, len(docs), k1=K1_, b=B_)
    tgt = temporal_target(q, parse_dt(str(inst.get("question_date") or "")))
    if tgt:
        dates = {sid: parse_dt(x) for sid, x in
                 zip(map(str, inst.get("haystack_session_ids") or []),
                     inst.get("haystack_dates") or [])}
        s = apply_time_prior(s, dates, tgt[0], tgt[1], 0.3)
    return ranked(s, docs)


def context_for(inst: dict, sids: list[str], mode: str) -> str:
    dates = dict(zip(map(str, inst.get("haystack_session_ids") or []),
                     inst.get("haystack_dates") or []))
    raw = dict(zip(map(str, inst.get("haystack_session_ids") or []),
                   inst.get("haystack_sessions") or []))
    qterms = {w for w in tokenize(str(inst.get("question") or ""))
              if len(w) >= 3}
    parts = []
    for i, sid in enumerate(sids, 1):
        text = session_text(raw.get(sid) or [])
        text = (text[:CAP] if mode == "full"
                else best_window(text, qterms, SNIP))
        parts.append(f"## Session {i} ({dates.get(sid, 'unknown date')})\n{text}")
    return "\n\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--reader", default="haiku")
    ap.add_argument("--judge", default="sonnet")
    ap.add_argument("--timeout", type=int, default=120)
    args = ap.parse_args()

    print(f"loading {args.data} …", flush=True)
    instances = json.loads(Path(args.data).read_text(encoding="utf-8"))
    sample = []
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
        if qidx % 2 == 1:          # dev half only
            continue
        sample.append(inst)
        if len(sample) >= args.n:
            break
    print(f"sample: {len(sample)} dev questions", flush=True)

    cfg = config.load_config()
    reader = support.completer("claude", args.reader, cfg, args.timeout)
    judge = support.completer("claude", args.judge, cfg, args.timeout)

    results = {"full3": [], "snip3": []}
    tokens = {"full3": [], "snip3": []}
    t0 = time.perf_counter()
    for i, inst in enumerate(sample, 1):
        docs = prep_docs([str(s) for s in inst.get("haystack_session_ids") or []],
                         inst.get("haystack_sessions") or [])
        top3 = tuned_order(inst, docs)[:3]
        q = str(inst.get("question") or "")
        gold = str(inst.get("answer") or "")
        for mode, key in (("full", "full3"), ("snip", "snip3")):
            ctx = context_for(inst, top3, mode)
            tokens[key].append(len(ctx) // EST)
            ans = (reader(READER_PROMPT.format(
                context=ctx, qdate=inst.get("question_date", "?"),
                question=q)) or "").strip()
            if is_abstention(ans):
                results[key].append({"qid": inst.get("question_id"),
                                     "correct": False, "verdict": "abstained",
                                     "answer": ans[:200]})
                continue
            v = (judge(JUDGE_PROMPT.format(question=q, gold=gold, hyp=ans))
                 or "").strip().lower()
            results[key].append({"qid": inst.get("question_id"),
                                 "correct": v.startswith("yes"),
                                 "verdict": v[:10], "answer": ans[:200]})
        if i % 10 == 0:
            print(f"  {i}/{len(sample)} ({time.perf_counter()-t0:.0f}s)",
                  flush=True)

    out = {"meta": {"date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "n": len(sample), "split": "dev-sample",
                    "reader": args.reader, "judge": args.judge,
                    "snippet_chars": SNIP, "full_cap_chars": CAP},
           "summary": {}}
    for key in ("full3", "snip3"):
        acc = sum(r["correct"] for r in results[key]) / max(1, len(results[key]))
        abst = sum(r["verdict"] == "abstained" for r in results[key])
        mt = sum(tokens[key]) / max(1, len(tokens[key]))
        out["summary"][key] = {"accuracy": round(acc, 3),
                               "abstained": abst,
                               "mean_ctx_tokens": int(mt)}
        print(f"{key}: acc {acc:.3f}  abstained {abst}  "
              f"mean ctx tokens {int(mt):,}", flush=True)
    out["detail"] = results
    RES.mkdir(parents=True, exist_ok=True)
    p = RES / f"snippet-e2e-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False),
                 encoding="utf-8")
    print(f"written: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
