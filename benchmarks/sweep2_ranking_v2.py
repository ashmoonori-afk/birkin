"""Ranking-v2 round 4: targeted fixes for the measured error classes (dev only).

From the round-3 error manifest (27 errors at k1=0.9 b=0.5 w_user=3):
  - 14/27 sit at rank 2            -> tie-break rerank, guarded by score gap
  - 7 temporal-reasoning errors    -> date prior from question_date/haystack_dates
  - top-1 wrong docs often cover MORE query terms -> idf emphasis, not coverage

Conditions (all arithmetic; tuned on DEV split only):
  base       bm25f @ k1=0.9 b=0.5 w_user=3 (round-3 winner)
  idfp       query-term weight = idf^P (emphasize rare anchors)
  tie        when top-2 scores are within EPS, rerank top-3 by span proximity
  time       for queries with a parseable relative-date cue, multiply scores
             by a window prior centered on the referenced date
  combo      base + tie + time (+ idfp if it wins alone)

Usage:
  python benchmarks/sweep2_ranking_v2.py --data <dir>/longmemeval_s_cleaned.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time as _time
from datetime import datetime, timedelta
from pathlib import Path

from _lme_common import metrics
from bench_ranking_v2 import (build_postings, bm25_weighted, prep_docs,
                              ranked, span_bonus)
from birkin.mnemosyne import tokenize

RES = Path("benchmarks/results")
HYBRID_BAR = {"recall@1": 0.894, "recall@5": 0.977, "mrr": 0.931}
K1_, B_, WU_ = 0.9, 0.5, 3.0                      # round-3 dev winner

_DATE_RE = re.compile(r"(\d{4})/(\d{2})/(\d{2})")
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday"]


def parse_dt(s: str) -> datetime | None:
    m = _DATE_RE.search(s or "")
    return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def temporal_target(question: str, qdate: datetime | None
                    ) -> tuple[datetime, float] | None:
    """(target date, window sigma in days) for a parseable relative cue."""
    if qdate is None:
        return None
    q = question.lower()
    m = re.search(r"(\d+|a|one|two|three|four|five|six|seven|eight|nine|ten)"
                  r"\s+(day|week|month)s?\s+ago", q)
    words = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    if m:
        n = words.get(m.group(1), None)
        n = int(m.group(1)) if n is None and m.group(1).isdigit() else n
        if n:
            unit = m.group(2)
            days = n * (1 if unit == "day" else 7 if unit == "week" else 30)
            sigma = max(1.5, days * 0.15)          # looser window further back
            return qdate - timedelta(days=days), sigma
    if "yesterday" in q:
        return qdate - timedelta(days=1), 1.0
    m = re.search(r"last\s+(" + "|".join(_WEEKDAYS) + r")", q)
    if m:
        target_wd = _WEEKDAYS.index(m.group(1))
        delta = (qdate.weekday() - target_wd) % 7 or 7
        return qdate - timedelta(days=delta), 1.5
    return None


def apply_time_prior(scores: dict[str, float], dates: dict[str, datetime | None],
                     target: datetime, sigma: float, lam: float) -> dict[str, float]:
    out = {}
    for sid, sc in scores.items():
        d = dates.get(sid)
        if d is None:
            out[sid] = sc
            continue
        dist = abs((d - target).days)
        out[sid] = sc * (1.0 + lam * math.exp(-(dist * dist) / (2 * sigma * sigma)))
    return out


def tie_break(order: list[str], scores: dict[str, float], docs: dict,
              qterms: set[str], eps: float, window: int, alpha: float
              ) -> list[str]:
    """If top-2 are within eps (relative), rerank top-3 by score + proximity."""
    if len(order) < 2:
        return order
    s1 = scores.get(order[0], 0.0)
    s2 = scores.get(order[1], 0.0)
    if s1 <= 0 or (s1 - s2) / s1 > eps:
        return order
    head = order[:3]
    top = s1 or 1.0
    resc = {sid: scores.get(sid, 0.0) / top
            + alpha * span_bonus(qterms, docs[sid]["toks"], window)
            for sid in head}
    return sorted(head, key=lambda x: -resc[x]) + order[3:]


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
        dates = {sid: parse_dt(d) for sid, d in
                 zip(sids, inst.get("haystack_dates") or [])}
        qs.append({"qid": qid, "q": str(inst.get("question") or ""),
                   "type": str(inst.get("question_type") or "?"),
                   "evidence": evidence,
                   "qdate": parse_dt(str(inst.get("question_date") or "")),
                   "dates": dates,
                   "docs": prep_docs(sids, inst.get("haystack_sessions") or [])})
    print(f"{args.split} questions: {len(qs)}", flush=True)

    # precompute base scores once per question (postings reused across conds)
    t0 = _time.perf_counter()
    for item in qs:
        postings, doclens, avgdl = build_postings(item["docs"], w_user=WU_)
        item["ppda"] = (postings, doclens, avgdl)
        toks = tokenize(item["q"])
        item["qtoks"] = toks
        n = len(item["docs"])
        item["idf"] = {}
        for t in set(toks):
            df = len(postings.get(t, {}))
            item["idf"][t] = math.log(1 + (n - df + 0.5) / (df + 0.5))
    print(f"precompute {_time.perf_counter()-t0:.0f}s", flush=True)

    def base_scores(item, idf_p: float = 0.0) -> dict[str, float]:
        postings, doclens, avgdl = item["ppda"]
        qw = {t: (item["idf"][t] ** idf_p if idf_p else 1.0)
              for t in set(item["qtoks"])}
        return bm25_weighted(qw, postings, doclens, avgdl, len(item["docs"]),
                             k1=K1_, b=B_)

    conds: dict[str, dict] = {}

    def run(name: str, fn) -> None:
        ranks = []
        for item in qs:
            ranks.append(first_hit(fn(item), item["evidence"]))
        conds[name] = metrics(ranks)
        m = conds[name]
        print(f"{name:<26} R@1 {m['recall@1']:.3f} R@5 {m['recall@5']:.3f} "
              f"R@10 {m['recall@10']:.3f} MRR {m['mrr']:.3f}", flush=True)

    def f_final(it):
        """FROZEN final config (dev-tuned, then evaluated once on test):
        bm25f(w_user=3, k1=0.9, b=0.5) + query idf^1 + time prior lam=0.3."""
        s = base_scores(it, 1.0)
        tgt = temporal_target(it["q"], it["qdate"])
        if tgt:
            s = apply_time_prior(s, it["dates"], tgt[0], tgt[1], 0.3)
        return ranked(s, it["docs"])

    if args.split == "dev":
        run("base", lambda it: ranked(base_scores(it), it["docs"]))
        for p in (0.5, 1.0, 1.5, 2.0):
            run(f"idfp_{p}",
                lambda it, p=p: ranked(base_scores(it, p), it["docs"]))
        for p in (1.0, 1.5):
            def f_idfp_time(it, p=p):
                s = base_scores(it, p)
                tgt = temporal_target(it["q"], it["qdate"])
                if tgt:
                    s = apply_time_prior(s, it["dates"], tgt[0], tgt[1], 0.3)
                return ranked(s, it["docs"])
            run(f"idfp{p}+time0.3", f_idfp_time)
        for eps, win, al in ((0.05, 24, 0.5), (0.10, 24, 0.5), (0.10, 48, 0.3)):
            def f_tie(it, eps=eps, win=win, al=al):
                s = base_scores(it)
                return tie_break(ranked(s, it["docs"]), s, it["docs"],
                                 set(it["qtoks"]), eps, win, al)
            run(f"tie_e{eps}_w{win}_a{al}", f_tie)
        for lam in (0.3, 0.6, 1.0):
            def f_time(it, lam=lam):
                s = base_scores(it)
                tgt = temporal_target(it["q"], it["qdate"])
                if tgt:
                    s = apply_time_prior(s, it["dates"], tgt[0], tgt[1], lam)
                return ranked(s, it["docs"])
            run(f"time_l{lam}", f_time)

        def f_combo(it, eps=0.10, win=24, al=0.5, lam=0.6):
            s = base_scores(it)
            tgt = temporal_target(it["q"], it["qdate"])
            if tgt:
                s = apply_time_prior(s, it["dates"], tgt[0], tgt[1], lam)
            return tie_break(ranked(s, it["docs"]), s, it["docs"],
                             set(it["qtoks"]), eps, win, al)
        run("combo_tie+time", f_combo)
        run("FINAL(frozen)", f_final)
    else:
        # test/full: plain bm25 reference + the one frozen config, nothing else
        def f_bm25_plain(it):
            postings, doclens, avgdl = build_postings(it["docs"], w_user=1.0)
            qw = {t: 1.0 for t in set(it["qtoks"])}
            return ranked(bm25_weighted(qw, postings, doclens, avgdl,
                                        len(it["docs"])), it["docs"])
        run("bm25(reference)", f_bm25_plain)
        run("FINAL(frozen)", f_final)

    out = {"meta": {"date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "split": args.split, "n": len(qs),
                    "base_params": {"k1": K1_, "b": B_, "w_user": WU_},
                    "hybrid_bar": HYBRID_BAR},
           "conditions": conds}
    RES.mkdir(parents=True, exist_ok=True)
    p = RES / (f"rankingv2-sweep2-{args.split}-"
               f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
    p.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"hybrid bar: {HYBRID_BAR}")
    print(f"written: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
