"""Generate the paper's benchmark figures from the committed result JSONs.

Every number is read from benchmarks/results/ — nothing hand-entered.
Style follows the dataviz skill: validated categorical palette, thin marks,
direct value labels (contrast relief), recessive axes, no dual axes.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]          # birkin repo root
RES = ROOT / "benchmarks" / "results"
OUT = Path(__file__).resolve().parent

# validated palette (dataviz reference instance, slots 1,2,3,5,6)
BLUE, AQUA, YELLOW, VIOLET, RED = ("#2a78d6", "#1baf7a", "#eda100",
                                   "#4a3aa7", "#e34948")
GRAY = "#8a8983"
SURFACE = "#ffffff"
INK, INK2 = "#1a1a19", "#5f5e56"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "font.family": "DejaVu Sans", "font.size": 9,
    "axes.edgecolor": "#d8d7cf", "axes.linewidth": 0.8,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK,
})


def _load(name: str) -> dict:
    return json.loads((RES / name).read_text(encoding="utf-8-sig"))


def _bar_labels(ax, bars, fmt="{:.3f}", dy=0.008):
    for b in bars:
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + dy,
                fmt.format(b.get_height()), ha="center", va="bottom",
                fontsize=7.5, color=INK)


def fig_retrieval() -> None:
    small = _load("lme-embed-cleaned-20260705.json")
    large = _load("lme-embed-cleaned-bgelarge-20260707.json")
    strong = _load("dense-strong-20260711.json")     # review-driven: chunked/RRF-swept
    tuned = _load("rankingv2-sweep2-full-20260711-161601.json")["conditions"]
    subs = _load("longmemeval-cleaned-20260703.json")["overall"]["substring_naive"]
    systems = [
        ("BM25\n(ours)", small["bm25"], BLUE),
        ("tuned lex.\n(ours)", tuned["FINAL(frozen)"], "#0f4f9e"),  # blue: dark
        ("bge-sm\ntrunc", small["embed"], "#5fc9a1"),        # aqua ramp: light
        ("bge-lg\ntrunc", large["embed"], "#0f8a5f"),        # aqua ramp: dark
        ("bge-sm\nchunked", strong["dense_chunk"], "#0a5c40"),  # aqua: darkest
        ("RRF\nk=20", strong["rrf_k20"], VIOLET),
        ("substring\n(prior)", subs, GRAY),
    ]
    metrics = [("recall@1", "R@1"), ("recall@5", "R@5"), ("mrr", "MRR")]
    fig, axes = plt.subplots(1, 3, figsize=(11.6, 2.8), sharey=True)
    for ax, (key, label) in zip(axes, metrics):
        vals = [s[1][key] for s in systems]
        bars = ax.bar(range(len(systems)), vals,
                      color=[s[2] for s in systems], width=0.6)
        _bar_labels(ax, bars)
        ax.set_title(label, fontsize=10, color=INK)
        ax.set_xticks(range(len(systems)))
        ax.set_xticklabels([s[0] for s in systems], fontsize=6.8)
        ax.set_ylim(0, 1.12)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(length=0)
    fig.suptitle("LongMemEval-S session retrieval — same harness, 470 questions",
                 fontsize=10.5, color=INK, y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "fig_retrieval.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def fig_e2e() -> None:
    # per-type accuracy from the detail files (top5 full run + oracle run)
    top5 = json.loads((RES / "lme-e2e-top5-detail.json")
                      .read_text(encoding="utf-8-sig"))
    oracle = json.loads(
        (RES / "lme-e2e-oracle-rclaude-haiku-jclaude-sonnet-detail.json")
        .read_text(encoding="utf-8-sig"))

    # paired comparison: restrict top5 to the SAME question ids the oracle
    # condition answered, so both bars average over identical questions.
    def clean(rows, typ, qids=None):
        return [x for x in rows if x.get("type") == typ and "error" not in x
                and not x.get("abstention_q")
                and (qids is None or x["qid"] in qids)]

    types = ["single-session-user", "multi-session"]
    t5, orc, ns = [], [], []
    for t in types:
        o = clean(oracle, t)
        qids = {x["qid"] for x in o}
        p = clean(top5, t, qids)
        orc.append(sum(x["correct"] for x in o) / len(o))
        t5.append(sum(x["correct"] for x in p) / len(p))
        ns.append(len(o))

    x = [0, 1]
    w = 0.34
    fig, ax = plt.subplots(figsize=(5.2, 2.9))
    b1 = ax.bar([i - w / 2 for i in x], t5, width=w, color=BLUE,
                label="BM25 top-5 → reader")
    b2 = ax.bar([i + w / 2 for i in x], orc, width=w, color=YELLOW,
                label="oracle evidence → reader")
    _bar_labels(ax, b1, "{:.2f}")
    _bar_labels(ax, b2, "{:.2f}")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{t}\n(paired, n={n})" for t, n in zip(types, ns)],
                       fontsize=8)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("answer accuracy", fontsize=8)
    ax.legend(frameon=False, fontsize=8, loc="lower center",
              bbox_to_anchor=(0.5, 1.02), ncol=2)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(length=0)
    ax.set_title("End-to-end QA: retrieval loss vs reader loss (haiku reader)",
                 fontsize=10, color=INK, pad=28)
    fig.tight_layout()
    fig.savefig(OUT / "fig_e2e.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def fig_decay() -> None:
    eff = _load("bench-20260703.json")["decay_curve"]["eff"]
    series = [("never accessed", "never_accessed", GRAY),
              ("one write", "single_write", AQUA),
              ("five spaced touches", "five_spaced_touches", BLUE)]
    fig, ax = plt.subplots(figsize=(5.6, 2.9))
    for label, key, color in series:
        pts = sorted(((int(d), v) for d, v in eff[key].items()),
                     key=lambda p: p[0])
        xs, ys = zip(*pts)
        ax.plot(xs, ys, color=color, linewidth=2, label=label)
        ax.scatter(xs, ys, s=10, color=color, zorder=3)
    ax.axhline(0.1, color=RED, linewidth=1, linestyle=(0, (4, 3)))
    ax.text(360, 0.115, "stale threshold (eff < 0.1)", ha="right",
            fontsize=7.5, color=RED)
    ax.set_xlabel("days since last access", fontsize=8)
    ax.set_ylabel("effective strength", fontsize=8)
    ax.set_xlim(-5, 370)
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(length=0)
    ax.set_title("Usage-driven Ebbinghaus decay (H5): spaced access buys months",
                 fontsize=10, color=INK)
    fig.tight_layout()
    fig.savefig(OUT / "fig_decay.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def fig_hard() -> None:
    import glob
    import random
    import statistics as st
    engines = [("Claude sonnet", "hardlink-claude-sonnet-v6-clean-*.json",
                "hardlink-claude-sonnet-fixtureB-once-*.json"),
               ("Claude haiku", "hardlink-claude-haiku-v6-clean-*.json",
                "hardlink-claude-haiku-fixtureB-once-*.json"),
               ("Codex spark", "hardlink-codex-*-v6-clean-*.json",
                "hardlink-codex-*-fixtureB-once-*.json")]

    def boot_ci(vals, n=10000, seed=7):
        rng = random.Random(seed)
        means = sorted(st.mean(rng.choices(vals, k=len(vals)))
                       for _ in range(n))
        return means[int(0.025 * n)], means[int(0.975 * n)]

    recall, prec, r_err, p_err, b_rec, b_prec = [], [], [], [], [], []
    for _, pat, pat_b in engines:
        rs, ps = [], []
        for f in glob.glob(str(RES / pat)):
            d = json.loads(Path(f).read_text(encoding="utf-8-sig"))
            rs.append(d["link_recall"])
            ps.append(d["link_precision"])
        recall.append(st.mean(rs)); prec.append(st.mean(ps))
        lo, hi = boot_ci(rs)
        r_err.append((st.mean(rs) - lo, hi - st.mean(rs)))
        lo, hi = boot_ci(ps)
        p_err.append((st.mean(ps) - lo, hi - st.mean(ps)))
        fb = json.loads(Path(glob.glob(str(RES / pat_b))[0])
                        .read_text(encoding="utf-8-sig"))
        b_rec.append(fb["link_recall"]); b_prec.append(fb["link_precision"])
    x = range(len(engines)); w = 0.34
    fig, ax = plt.subplots(figsize=(5.6, 2.9))
    b1 = ax.bar([i - w / 2 for i in x], recall, width=w, color=BLUE,
                yerr=list(zip(*r_err)), capsize=3,
                error_kw={"ecolor": INK2, "elinewidth": 1}, label="link recall")
    b2 = ax.bar([i + w / 2 for i in x], prec, width=w, color=YELLOW,
                yerr=list(zip(*p_err)), capsize=3,
                error_kw={"ecolor": INK2, "elinewidth": 1}, label="link precision")
    for bars in (b1, b2):
        for b in bars:
            ax.text(b.get_x() + b.get_width() / 2, 0.04,
                    f"{b.get_height():.2f}", ha="center", va="bottom",
                    fontsize=8, color="#ffffff", fontweight="bold")
    # hidden fixture B: single frozen pass per engine, drawn as diamonds
    ax.scatter([i - w / 2 for i in x], b_rec, marker="D", s=34, zorder=4,
               facecolor="#ffffff", edgecolor=BLUE, linewidth=1.4,
               label="fixture B (1 frozen pass)")
    ax.scatter([i + w / 2 for i in x], b_prec, marker="D", s=34, zorder=4,
               facecolor="#ffffff", edgecolor="#a06c00", linewidth=1.4)
    ax.set_xticks(list(x))
    ax.set_xticklabels([e[0] + "\n(n=10)" for e in engines], fontsize=8)
    ax.set_ylim(0, 1.08)
    ax.legend(frameon=False, fontsize=7.5, loc="lower center", ncol=3,
              bbox_to_anchor=(0.5, 1.01))
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(length=0)
    ax.set_title("Hard curation fixture (232 pairs, fixture-disjoint prompt) — "
                 "mean, bootstrap 95% CI; diamonds = hidden fixture B",
                 fontsize=9, color=INK, pad=24)
    fig.tight_layout()
    fig.savefig(OUT / "fig_hard.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def fig_realvault() -> None:
    import glob
    d = json.loads(Path(sorted(glob.glob(str(RES / "realvault-2*.json")))[-1])
                   .read_text(encoding="utf-8-sig"))
    before, after = d["before"], d["after"]
    fig, (axl, axr) = plt.subplots(
        1, 2, figsize=(8.6, 2.9), gridspec_kw={"width_ratios": [1, 1.35]})
    # left: structure (log scale) — zones and links, before vs after
    cats = [("zones", len(before["graph"]["zones"]),
             len(after["graph"]["zones"])),
            ("links", max(before["graph"]["directed_links"], 1),
             after["graph"]["directed_links"])]
    xs = range(len(cats)); w = 0.34
    bb = axl.bar([i - w / 2 for i in xs], [c[1] for c in cats], width=w,
                 color=GRAY, label="before")
    ba = axl.bar([i + w / 2 for i in xs], [c[2] for c in cats], width=w,
                 color=BLUE, label="after")
    axl.set_yscale("log")
    for bars in (bb, ba):
        for b in bars:
            axl.text(b.get_x() + b.get_width() / 2, b.get_height() * 1.15,
                     f"{int(b.get_height()):,}", ha="center", va="bottom",
                     fontsize=7.5, color=INK)
    axl.set_xticks(list(xs))
    axl.set_xticklabels([c[0] for c in cats], fontsize=8)
    axl.set_ylim(0.8, 20000)
    axl.set_title("structure (log scale)", fontsize=9, color=INK)
    axl.legend(frameon=False, fontsize=7.5, loc="upper left")
    axl.spines[["top", "right"]].set_visible(False)
    axl.tick_params(length=0)
    # right: retrieval on the 40 frozen queries — flat
    keys = [("recall@1", "R@1"), ("recall@5", "R@5"), ("recall@10", "R@10"),
            ("mrr", "MRR"), ("recall_top3+links", "R@3+links")]
    xs2 = range(len(keys))
    bb = axr.bar([i - w / 2 for i in xs2],
                 [before["retrieval"][k] for k, _ in keys], width=w,
                 color=GRAY, label="before")
    ba = axr.bar([i + w / 2 for i in xs2],
                 [after["retrieval"][k] for k, _ in keys], width=w,
                 color=BLUE, label="after")
    for bars in (bb, ba):
        _bar_labels(axr, bars, "{:.2f}", dy=0.004)
    axr.set_xticks(list(xs2))
    axr.set_xticklabels([lbl for _, lbl in keys], fontsize=8)
    axr.set_ylim(0, 0.42)
    axr.set_title("retrieval, 40 frozen queries", fontsize=9, color=INK)
    axr.spines[["top", "right"]].set_visible(False)
    axr.tick_params(length=0)
    fig.suptitle("One curation pass on a real 1,910-note vault: "
                 "structure moves, top-k does not",
                 fontsize=10, color=INK, y=1.04)
    fig.tight_layout()
    fig.savefig(OUT / "fig_realvault.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    fig_retrieval()
    fig_e2e()
    fig_decay()
    fig_hard()
    fig_realvault()
    print("figures written to", OUT)
