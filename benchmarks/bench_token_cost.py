"""Token-cost benchmark: what does each memory strategy PUT INTO CONTEXT?

Retrieval quality says which strategy finds the evidence; this measures what
each one costs in prompt tokens to do so. No LLM calls — pure counting.
Token estimator: chars/4 (the standard rule of thumb; we report raw chars
too, so any tokenizer can be substituted).

Corpus A — LongMemEval-S (470 questions), tokens per question to answer:
    full_haystack   long-context approach: every session in the prompt
    top5_bm25       the paper's e2e pipeline (top-5 sessions, 12k-char cap)
    top5_tuned      same, ranked by the tuned lexical stack (§5.1)
    top3_tuned      the cheaper cut
    oracle          evidence sessions only (lower bound)
  Each strategy also reports evidence coverage (does the context contain a
  gold session?) so cost is never read without its quality.

Corpus B — real 1,910-note vault, tokens per query that reach the context:
    whole_vault     naive "load everything"
    digest+top8     what Mnemosyne actually injects: the rendered digest
                    (always-on layer) + top-8 search results (metadata) +
                    the top-3 note bodies (what an agent typically opens)

Usage:
  python benchmarks/bench_token_cost.py --data <dir>/longmemeval_s_cleaned.json
      [--vault C:/.../bk-realvault-v_l2qem9/vault] [--limit 470]
"""

from __future__ import annotations

import argparse
import json
import statistics as stats
import time
from datetime import datetime
from pathlib import Path

from bench_ranking_v2 import build_postings, bm25_weighted, prep_docs, ranked
from sweep2_ranking_v2 import (K1_, B_, WU_, apply_time_prior, parse_dt,
                               temporal_target)
from birkin.mnemosyne import tokenize

RES = Path("benchmarks/results")
CAP = 12_000                       # per-session char cap (mirrors bench_lme_e2e)
EST = 4                            # chars per token (rule-of-thumb estimator)


def toks_of(chars: int) -> int:
    return chars // EST


def lme_part(data: str, limit: int) -> dict:
    print(f"loading {data} …", flush=True)
    instances = json.loads(Path(data).read_text(encoding="utf-8"))
    rows = {k: [] for k in ("full_haystack", "top5_bm25", "top5_tuned",
                            "top3_tuned", "oracle")}
    cover = {k: 0 for k in rows}
    used = 0
    t0 = time.perf_counter()
    for inst in instances:
        qid = str(inst.get("question_id", ""))
        evidence = set(map(str, inst.get("answer_session_ids") or []))
        if qid.endswith("_abs") or not evidence:
            continue
        sids = [str(s) for s in inst.get("haystack_session_ids") or []]
        sessions = inst.get("haystack_sessions") or []
        if not sids or not evidence & set(sids):
            continue
        if used >= limit:
            break
        used += 1
        q = str(inst.get("question") or "")
        docs = prep_docs(sids, sessions)
        raw_chars = {sid: sum(len(str(t.get("content") or ""))
                              for t in sess if isinstance(t, dict))
                     for sid, sess in zip(sids, sessions)}

        def cost(chosen: list[str], cap: bool = True) -> int:
            return sum(min(raw_chars[s], CAP) if cap else raw_chars[s]
                       for s in chosen)

        # bm25 ranking (plain) and tuned ranking (frozen §5.1 config)
        p, dl, av = build_postings(docs, w_user=1.0)
        qw = {t: 1.0 for t in set(tokenize(q))}
        order_bm = ranked(bm25_weighted(qw, p, dl, av, len(docs)), docs)
        p2, dl2, av2 = build_postings(docs, w_user=WU_)
        import math
        qw2 = {}
        for t in set(tokenize(q)):
            df = len(p2.get(t, {}))
            qw2[t] = math.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
        s2 = bm25_weighted(qw2, p2, dl2, av2, len(docs), k1=K1_, b=B_)
        tgt = temporal_target(q, parse_dt(str(inst.get("question_date") or "")))
        if tgt:
            dates = {sid: parse_dt(x) for sid, x in
                     zip(sids, inst.get("haystack_dates") or [])}
            s2 = apply_time_prior(s2, dates, tgt[0], tgt[1], 0.3)
        order_tu = ranked(s2, docs)

        picks = {"full_haystack": (list(docs), False),
                 "top5_bm25": (order_bm[:5], True),
                 "top5_tuned": (order_tu[:5], True),
                 "top3_tuned": (order_tu[:3], True),
                 "oracle": (sorted(evidence & set(docs)), True)}
        for k, (chosen, cap) in picks.items():
            rows[k].append(cost(chosen, cap))
            cover[k] += bool(evidence & set(chosen))
        if used % 100 == 0:
            print(f"  {used} done ({time.perf_counter()-t0:.0f}s)", flush=True)

    out = {}
    for k, v in rows.items():
        out[k] = {"mean_tokens": toks_of(int(stats.mean(v))),
                  "median_tokens": toks_of(int(stats.median(v))),
                  "mean_chars": int(stats.mean(v)),
                  "evidence_coverage": round(cover[k] / used, 3)}
    out["_n"] = used
    return out


def vault_part(vault: str) -> dict:
    from birkin import mnemosyne
    from birkin.memory import VaultMemory
    vp = Path(vault)
    dex = mnemosyne.Mnemosyne(vp)
    dex.refresh()
    entries = dex.entries()
    whole = sum((vp / e["rel"]).stat().st_size for e in entries.values()
                if (vp / e["rel"]).is_file())
    mem = VaultMemory({"vault_path": str(vp)})
    digest = mem.render()

    queries = json.loads((RES / "realvault-queries.json")
                         .read_text(encoding="utf-8"))["queries"]
    per_q = []
    for item in queries:
        hits = dex.search(item["query"], limit=8)
        meta_chars = sum(len(json.dumps(h, ensure_ascii=False)) for h in hits)
        body_chars = 0
        for h in hits[:3]:                     # agent opens top-3 bodies
            f = vp / h["rel"]
            if f.is_file():
                body_chars += min(f.stat().st_size, CAP)
        per_q.append(len(digest) + meta_chars + body_chars)
    return {"whole_vault": {"mean_tokens": toks_of(whole),
                            "mean_chars": whole},
            "digest+top8+3bodies": {
                "mean_tokens": toks_of(int(stats.mean(per_q))),
                "median_tokens": toks_of(int(stats.median(per_q))),
                "mean_chars": int(stats.mean(per_q)),
                "digest_chars": len(digest)},
            "_n_queries": len(per_q), "_notes": len(entries)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--vault",
                    default=r"C:\Users\lg\AppData\Local\Temp\bk-realvault-v_l2qem9\vault")
    ap.add_argument("--limit", type=int, default=470)
    args = ap.parse_args()

    result = {"meta": {"date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                       "estimator": f"chars/{EST}", "session_cap_chars": CAP},
              "longmemeval": lme_part(args.data, args.limit)}
    if Path(args.vault).is_dir():
        result["real_vault"] = vault_part(args.vault)
    else:
        print(f"vault not found, skipping corpus B: {args.vault}")

    lm = result["longmemeval"]
    base = lm["top5_tuned"]["mean_tokens"]
    print(f"\nLongMemEval (n={lm['_n']}) — mean tokens/question "
          f"(evidence coverage):")
    for k in ("full_haystack", "top5_bm25", "top5_tuned", "top3_tuned",
              "oracle"):
        m = lm[k]
        print(f"  {k:<14} {m['mean_tokens']:>8,}  (cov {m['evidence_coverage']}"
              f", ×{m['mean_tokens']/max(1,base):.1f} vs top5_tuned)")
    if "real_vault" in result:
        rv = result["real_vault"]
        print(f"\nReal vault ({rv['_notes']} notes, {rv['_n_queries']} queries)"
              f" — tokens into context per query:")
        print(f"  whole_vault          {rv['whole_vault']['mean_tokens']:>9,}")
        print(f"  digest+top8+3bodies  "
              f"{rv['digest+top8+3bodies']['mean_tokens']:>9,}  "
              f"(digest {toks_of(rv['digest+top8+3bodies']['digest_chars']):,} tok)")
    RES.mkdir(parents=True, exist_ok=True)
    p = RES / f"tokencost-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    p.write_text(json.dumps(result, indent=1, ensure_ascii=False),
                 encoding="utf-8")
    print(f"written: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
