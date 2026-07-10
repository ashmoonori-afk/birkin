"""Boost-weight sensitivity + interference (review criticism #3).

The 2x2 ablation only shows the boosts break ties. This measures what they
COST: with real (non-identical) bodies, how often does a frequently-used but
less-relevant note wrongly outrank a cold but more-relevant one?

Setup per trial: a target note T and a decoy D in the same corpus. D shares
the query's topic vocabulary only partially (BM25 should rank T > D on
relevance), but D is heavily rehearsed (5 spaced accesses -> eff ~2.25) and
lives in a hot zone; T is cold. For each (W_dyn, W_zone) grid point we count:

  win   = T still ranks above D          (relevance preserved)
  flip  = D outranks T                   (usage interference — the failure)

Also reports the tie-break benefit on identical twins (the 2x2's metric) at
each grid point, so cost and benefit sit side by side.
"""

from __future__ import annotations

import json
import random
import tempfile
from datetime import datetime
from datetime import timedelta
from pathlib import Path

from birkin import mnemosyne
from bench import TOPICS, NOW, _write_note

GRID_DYN = (0.0, 0.1, 0.3, 0.6, 1.0)
GRID_ZONE = (0.0, 0.1, 0.2, 0.4)
N_PAIRS = 30


def build(root: Path, rng: random.Random):
    vault = root / "vault"
    vault.mkdir(parents=True)
    bank = TOPICS["kubernetes"]
    other = TOPICS["cooking"]
    pairs = []          # (target, decoy, query)  — clear relevance gap
    marginal = []       # (target, decoy, query)  — near-tie relevance
    twins = []          # (warm_twin, cold_twin, query) — tie-break benefit
    for i in range(N_PAIRS):
        anchor = f"reltok{i}"
        # target: strongly on-topic (anchor x3 + topic terms)
        t_body = f"{anchor} {anchor} {anchor} " + " ".join(rng.sample(bank, 8))
        # decoy: mentions the anchor once, mostly other-topic
        d_body = f"{anchor} " + " ".join(rng.sample(other, 10))
        t = _write_note(vault, f"target {i}", t_body, zone="coldzone")
        d = _write_note(vault, f"decoy {i}", d_body, zone="hotzone")
        pairs.append((t, d, f"{anchor} " + " ".join(rng.sample(bank, 2))))
        # marginal decoy: nearly as relevant (anchor x2, on-topic terms)
        m_anchor = f"margtok{i}"
        mt_body = (f"{m_anchor} {m_anchor} {m_anchor} "
                   + " ".join(rng.sample(bank, 8)))
        md_body = f"{m_anchor} {m_anchor} " + " ".join(rng.sample(bank, 8))
        mt = _write_note(vault, f"mtarget {i}", mt_body, zone="coldzone")
        md = _write_note(vault, f"mdecoy {i}", md_body, zone="hotzone")
        marginal.append((mt, md,
                         f"{m_anchor} " + " ".join(rng.sample(bank, 2))))
        tw_body = f"twintok{i} " + " ".join(rng.sample(bank, 8))
        a = _write_note(vault, f"twin warm {i}", tw_body, zone="hotzone")
        b = _write_note(vault, f"twin cold {i}", tw_body, zone="coldzone")
        twins.append((a, b, f"twintok{i} " + " ".join(rng.sample(bank, 2))))
    fillers = [_write_note(vault, f"hot filler {i}",
                           " ".join(rng.choices(bank, k=10)), zone="hotzone")
               for i in range(6)]
    eng = mnemosyne.Mnemosyne(vault)
    eng.rebuild()
    for _t, d, _q in pairs:                 # rehearse the DECOYS
        for k in range(5):
            eng.record_access(d, now=NOW - timedelta(hours=2 * (5 - k)))
    for _t, d, _q in marginal:
        for k in range(5):
            eng.record_access(d, now=NOW - timedelta(hours=2 * (5 - k)))
    for a, _b, _q in twins:                 # rehearse warm twins
        for k in range(5):
            eng.record_access(a, now=NOW - timedelta(hours=2 * (5 - k)))
    for i, f in enumerate(fillers * 5):     # heat the hot zone
        eng.record_access(f, now=NOW - timedelta(hours=i + 1))
    return eng, pairs, marginal, twins


def rate(eng, items, wd: float, wz: float) -> float:
    sd, sz = mnemosyne.W_DYN, mnemosyne.W_ZONE
    mnemosyne.W_DYN, mnemosyne.W_ZONE = wd, wz
    try:
        wins = 0
        for first, second, q in items:
            score = {h["slug"]: h["score"]
                     for h in eng.search(q, limit=50, now=NOW)}
            wins += score.get(first, 0.0) > score.get(second, 0.0)
        return round(wins / len(items), 3)
    finally:
        mnemosyne.W_DYN, mnemosyne.W_ZONE = sd, sz


def main() -> int:
    rng = random.Random(11)
    root = Path(tempfile.mkdtemp(prefix="bk-sens-"))
    eng, pairs, marginal, twins = build(root, rng)
    grid = {}
    for wd in GRID_DYN:
        for wz in GRID_ZONE:
            key = f"dyn={wd},zone={wz}"
            grid[key] = {
                # relevance preserved: target above rehearsed decoy
                "target_above_decoy": rate(eng, pairs, wd, wz),
                # near-tie relevance: where interference CAN flip ranks
                "marginal_target_above_decoy": rate(eng, marginal, wd, wz),
                # tie-break benefit: warm twin above cold twin
                "warm_twin_wins": rate(eng, twins, wd, wz),
            }
            print(key, grid[key])
    result = {"meta": {"date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                       "n_pairs": N_PAIRS,
                       "note": "decoys rehearsed 5x + hot zone; targets cold"},
              "grid": grid,
              "default": grid["dyn=0.3,zone=0.2"]}
    out = Path("benchmarks/results")
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"weight-sensitivity-{datetime.now().strftime('%Y%m%d')}.json"
    p.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print("written:", p)
    import shutil
    shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
