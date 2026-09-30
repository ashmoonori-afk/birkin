# Semantic memory / LongMemEval results

## Published fixture run

These numbers are **fixture-based**, not public LongMemEval leaderboard results. This historical run uses the committed 14-question mini set (`2 x 7` required categories), deterministic local hash embeddings, and a deterministic reader that extracts an `Answer:` line from the assembled top-1 snippet. Retrieval recall is measured at 5; answer accuracy is measured after top-1 context assembly. The deliberate difference makes the retrieval-versus-reading bottleneck measurable instead of conflating the stages.

Command (Python 3.12, Windows):

```powershell
$env:PYTHONUTF8=1
$env:PYTHONIOENCODING='utf-8'
python benchmarks/bench_memory_longmemeval.py `
  --out benchmarks/results/memory-longmemeval-fixture.json
```

Run date: 2026-08-14. `R` = evidence retrieval recall; `A` = final answer accuracy.

| Category (n=2 each) | lexical-only R / A | +vector R / A | +entity R / A | full R / A |
|---|---:|---:|---:|---:|
| single-session-user | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| single-session-assistant | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| single-session-preference | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| multi-session | 1.000 / 0.000 | 1.000 / 0.000 | 1.000 / 0.000 | 1.000 / 0.000 |
| temporal-reasoning | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| knowledge-update | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| abstention | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| **Overall (n=14)** | **1.000 / 0.857** | **1.000 / 0.857** | **1.000 / 0.857** | **1.000 / 0.857** |

For abstention examples there is no gold evidence to miss, so retrieval recall is vacuously `1.000`; answer accuracy measures whether the reader abstains.

| Configuration | Signals | Tokens/query | Latency p50 (ms) | Latency p95 (ms) | Storage bytes |
|---|---|---:|---:|---:|---:|
| lexical-only | lexical | 11.9 | 2.847 | 5.962 | 26,101 |
| +vector | lexical, vector | 12.4 | 3.740 | 8.176 | 26,100 |
| +entity | lexical, entity | 12.4 | 3.351 | 8.482 | 26,105 |
| full | lexical, vector, entity, time | 12.4 | 3.613 | 8.136 | 26,104 |

Storage is the total bytes written across all 14 isolated per-question vaults, including Markdown and Birkin's derived index/dynamics sidecars. Small byte differences come from serialized file-stat fingerprints. Latencies are wall-clock search latency on this host and should be rerun on the deployment machine.

The fixture shows the intended diagnostic split: all evidence is found at retrieval depth 5, while only 85.7% of final answers succeed after top-1 context assembly. The 14.3-point aggregate gap (and the multi-session `1.000` versus `0.000` gap) confirms that adding retrievers alone does not fix context selection and reading. This mirrors the prior real evaluation's larger `96.8%` retrieval versus `53.8%` answer gap.

## Public dataset run

This run uses the real 500-question `longmemeval_s_cleaned.json` public release, not the committed fixture. Dataset provenance:

- Hugging Face dataset: [`xiaowu0162/longmemeval-cleaned`](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)
- Repository snapshot: `98d7416c24c778c2fee6e6f3006e7a073259d48f`
- File SHA-256: `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`
- File size: `277,383,467` bytes
- Run timestamp: `2026-08-14T04:55:37+00:00`

Retrieval recall is the fraction of questions for which at least one gold answer session appears in the top 5. The public small split contains six question categories and no abstention examples. `+vector` and `full` use the harness's dependency-free `deterministic-hash-v1` vector backend; this run does not claim sentence-transformer performance.

| Category | n | lexical-only R | +vector R | +entity R | full R |
|---|---:|---:|---:|---:|---:|
| single-session-user | 70 | 1.000 | 0.986 | 1.000 | 0.986 |
| single-session-assistant | 56 | 1.000 | 1.000 | 1.000 | 1.000 |
| single-session-preference | 30 | 0.867 | 0.867 | 0.867 | 0.867 |
| multi-session | 133 | 0.970 | 0.970 | 0.970 | 0.970 |
| temporal-reasoning | 133 | 0.977 | 0.970 | 0.977 | 0.970 |
| knowledge-update | 78 | 0.987 | 0.987 | 0.987 | 0.987 |
| **Overall** | **500** | **0.976** | **0.972** | **0.976** | **0.972** |

| Configuration | Signals | Tokens/query | Latency p50 (ms) | Latency p95 (ms) | Storage bytes |
|---|---|---:|---:|---:|---:|
| lexical-only | lexical | 67.1 | 32.705 | 52.463 | 393,965,902 |
| +vector | lexical, vector | 67.1 | 35.018 | 53.820 | 393,965,877 |
| +entity | lexical, entity | 67.1 | 29.990 | 46.639 | 393,965,971 |
| full | lexical, vector, entity, time | 67.1 | 34.077 | 50.231 | 393,966,031 |

Storage is the total bytes written across 500 isolated per-question vaults. Tokens/query estimates the assembled top-1 context at four characters per token. Latencies are wall-clock search timings on this Windows host.

Answer accuracy was **not run** and is `null` in the raw JSON. `ollama`, `llama-cli`, `llama-server`, `llamafile`, and `lmstudio` were not present on this host, so there was no local answer model; fixture-reader answers were deliberately disabled rather than reported against public data.

Exact reproduction command (Git Bash, Python 3.12):

```bash
curl --fail --location \
  "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416c24c778c2fee6e6f3006e7a073259d48f/longmemeval_s_cleaned.json?download=true" \
  --output /c/Users/lg/Documents/Claude/Projects/Birkin/.dataset-cache/longmemeval/longmemeval_s_cleaned.json
sha256sum /c/Users/lg/Documents/Claude/Projects/Birkin/.dataset-cache/longmemeval/longmemeval_s_cleaned.json
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
C:/Users/lg/AppData/Local/Programs/Python/Python312/python.exe \
  benchmarks/bench_memory_longmemeval.py \
  --data C:/Users/lg/Documents/Claude/Projects/Birkin/.dataset-cache/longmemeval/longmemeval_s_cleaned.json \
  --retrieval-only \
  --out benchmarks/results/memory-longmemeval-public.json
```

To measure final-answer accuracy on another host, replace `--retrieval-only` with `--answer-command COMMAND`. The command must read one JSON object (`{"question": ..., "context": ...}`) from stdin and print only its answer.


## Multilingual lexical recall (birkin-mnemosyne 0.4.0 core)

The Unicode-aware tokenizer, the code-switch script bonus and the
zlib-compressed index cache of birkin-mnemosyne 0.4.0 were ported into both
lexical engines Birkin ships. The corpus is birkin-mnemosyne's public
retrieval benchmark (160 fictional gold notes: 40 English, 40 Korean, 20 each
Japanese, Chinese, Spanish, German; padded with generated distractors to 1000
notes). Three authors wrote one exact, one paraphrase and one code-switched
question per note; two of them (`gpt-6.1-sol`, `claude-fable-5.1`) wrote
independently from a notes-only export. The corpus is not vendored:

```bash
git clone --branch v0.4.0 https://github.com/ashmoonori-afk/birkin-mnemosyne
python benchmarks/bench_multilingual_retrieval.py \
  --corpus-dir birkin-mnemosyne/benchmarks/retrieval --json after.json
# the same script against another checkout of Birkin gives the other half:
python benchmarks/bench_multilingual_retrieval.py \
  --corpus-dir birkin-mnemosyne/benchmarks/retrieval --repo ../birkin-main --json before.json
python benchmarks/bench_multilingual_retrieval.py --compare before.json after.json
```

Run date: 2026-09-30, Linux; the quality numbers are identical under Python
3.13 and 3.14. `main` is commit `2d286503`. One
gold note per question; the gold note's declared cross-language siblings are
removed from the ranking before scoring. Constants were chosen on the dev
split; every number below is the test split.

#### `birkin.mnemosyne` (the engine behind `memory_search`): main -> this change (test split)

| notes | question set | lang | n | R@5 | MRR |
|---|---|---|---|---|---|
| 160 | all three authors | en | 252 | 0.425 -> 0.476 (+0.052) | 0.389 -> 0.423 (+0.034) |
| 160 | all three authors | ko | 243 | 0.733 -> 0.733 (+0.000) | 0.690 -> 0.690 (-0.000) |
| 160 | all three authors | ja | 99 | 0.869 -> 0.869 (+0.000) | 0.818 -> 0.818 (+0.000) |
| 160 | all three authors | zh | 135 | 0.881 -> 0.881 (+0.000) | 0.835 -> 0.835 (+0.000) |
| 160 | all three authors | es | 108 | 0.778 -> 0.759 (-0.019) | 0.692 -> 0.726 (+0.034) |
| 160 | all three authors | de | 135 | 0.785 -> 0.793 (+0.007) | 0.685 -> 0.728 (+0.043) |
| 160 | gpt-6.1-sol (independent) | en | 84 | 0.369 -> 0.393 (+0.024) | 0.365 -> 0.371 (+0.007) |
| 160 | gpt-6.1-sol (independent) | ko | 81 | 0.778 -> 0.778 (+0.000) | 0.731 -> 0.731 (+0.000) |
| 160 | gpt-6.1-sol (independent) | ja | 33 | 0.818 -> 0.818 (+0.000) | 0.844 -> 0.844 (+0.000) |
| 160 | gpt-6.1-sol (independent) | zh | 45 | 0.867 -> 0.867 (+0.000) | 0.810 -> 0.810 (+0.000) |
| 160 | gpt-6.1-sol (independent) | es | 36 | 0.722 -> 0.750 (+0.028) | 0.615 -> 0.705 (+0.090) |
| 160 | gpt-6.1-sol (independent) | de | 45 | 0.733 -> 0.756 (+0.022) | 0.628 -> 0.711 (+0.083) |
| 160 | claude-fable-5.1 (independent) | en | 84 | 0.440 -> 0.512 (+0.071) | 0.397 -> 0.430 (+0.033) |
| 160 | claude-fable-5.1 (independent) | ko | 81 | 0.704 -> 0.704 (+0.000) | 0.653 -> 0.653 (-0.000) |
| 160 | claude-fable-5.1 (independent) | ja | 33 | 0.909 -> 0.909 (+0.000) | 0.832 -> 0.832 (+0.000) |
| 160 | claude-fable-5.1 (independent) | zh | 45 | 0.933 -> 0.933 (+0.000) | 0.855 -> 0.855 (+0.000) |
| 160 | claude-fable-5.1 (independent) | es | 36 | 0.861 -> 0.806 (-0.056) | 0.761 -> 0.792 (+0.031) |
| 160 | claude-fable-5.1 (independent) | de | 45 | 0.844 -> 0.867 (+0.022) | 0.747 -> 0.782 (+0.035) |
| 1000 | all three authors | en | 252 | 0.444 -> 0.524 (+0.079) | 0.391 -> 0.443 (+0.051) |
| 1000 | all three authors | ko | 243 | 0.728 -> 0.728 (+0.000) | 0.679 -> 0.676 (-0.002) |
| 1000 | all three authors | ja | 99 | 0.889 -> 0.889 (+0.000) | 0.812 -> 0.812 (+0.000) |
| 1000 | all three authors | zh | 135 | 0.852 -> 0.852 (+0.000) | 0.802 -> 0.802 (+0.000) |
| 1000 | all three authors | es | 108 | 0.750 -> 0.741 (-0.009) | 0.676 -> 0.716 (+0.040) |
| 1000 | all three authors | de | 135 | 0.763 -> 0.785 (+0.022) | 0.675 -> 0.733 (+0.059) |
| 1000 | gpt-6.1-sol (independent) | en | 84 | 0.369 -> 0.440 (+0.071) | 0.366 -> 0.389 (+0.023) |
| 1000 | gpt-6.1-sol (independent) | ko | 81 | 0.778 -> 0.778 (+0.000) | 0.709 -> 0.709 (+0.000) |
| 1000 | gpt-6.1-sol (independent) | ja | 33 | 0.909 -> 0.909 (+0.000) | 0.843 -> 0.843 (+0.000) |
| 1000 | gpt-6.1-sol (independent) | zh | 45 | 0.822 -> 0.822 (+0.000) | 0.781 -> 0.781 (+0.000) |
| 1000 | gpt-6.1-sol (independent) | es | 36 | 0.750 -> 0.750 (+0.000) | 0.585 -> 0.703 (+0.118) |
| 1000 | gpt-6.1-sol (independent) | de | 45 | 0.711 -> 0.778 (+0.067) | 0.620 -> 0.712 (+0.091) |
| 1000 | claude-fable-5.1 (independent) | en | 84 | 0.440 -> 0.560 (+0.119) | 0.385 -> 0.459 (+0.074) |
| 1000 | claude-fable-5.1 (independent) | ko | 81 | 0.704 -> 0.704 (+0.000) | 0.649 -> 0.642 (-0.007) |
| 1000 | claude-fable-5.1 (independent) | ja | 33 | 0.879 -> 0.879 (+0.000) | 0.793 -> 0.793 (+0.000) |
| 1000 | claude-fable-5.1 (independent) | zh | 45 | 0.911 -> 0.911 (+0.000) | 0.852 -> 0.852 (+0.000) |
| 1000 | claude-fable-5.1 (independent) | es | 36 | 0.806 -> 0.806 (+0.000) | 0.762 -> 0.788 (+0.026) |
| 1000 | claude-fable-5.1 (independent) | de | 45 | 0.822 -> 0.844 (+0.022) | 0.728 -> 0.799 (+0.071) |

#### bundled `birkin_mnemosyne`: main -> this change (test split)

| notes | question set | lang | n | R@5 | MRR |
|---|---|---|---|---|---|
| 160 | all three authors | en | 252 | 0.679 -> 0.698 (+0.020) | 0.552 -> 0.592 (+0.040) |
| 160 | all three authors | ko | 243 | 0.658 -> 0.654 (-0.004) | 0.582 -> 0.578 (-0.004) |
| 160 | all three authors | ja | 99 | 0.061 -> 0.848 (+0.788) | 0.061 -> 0.794 (+0.733) |
| 160 | all three authors | zh | 135 | 0.000 -> 0.867 (+0.867) | 0.000 -> 0.818 (+0.818) |
| 160 | all three authors | es | 108 | 0.722 -> 0.769 (+0.046) | 0.615 -> 0.698 (+0.083) |
| 160 | all three authors | de | 135 | 0.733 -> 0.763 (+0.030) | 0.612 -> 0.690 (+0.078) |
| 160 | gpt-6.1-sol (independent) | en | 84 | 0.560 -> 0.607 (+0.048) | 0.463 -> 0.524 (+0.061) |
| 160 | gpt-6.1-sol (independent) | ko | 81 | 0.704 -> 0.679 (-0.025) | 0.607 -> 0.607 (+0.001) |
| 160 | gpt-6.1-sol (independent) | ja | 33 | 0.061 -> 0.818 (+0.758) | 0.061 -> 0.827 (+0.767) |
| 160 | gpt-6.1-sol (independent) | zh | 45 | 0.000 -> 0.867 (+0.867) | 0.000 -> 0.811 (+0.811) |
| 160 | gpt-6.1-sol (independent) | es | 36 | 0.583 -> 0.694 (+0.111) | 0.491 -> 0.628 (+0.137) |
| 160 | gpt-6.1-sol (independent) | de | 45 | 0.644 -> 0.689 (+0.044) | 0.537 -> 0.615 (+0.078) |
| 160 | claude-fable-5.1 (independent) | en | 84 | 0.750 -> 0.762 (+0.012) | 0.607 -> 0.647 (+0.040) |
| 160 | claude-fable-5.1 (independent) | ko | 81 | 0.580 -> 0.580 (+0.000) | 0.525 -> 0.529 (+0.004) |
| 160 | claude-fable-5.1 (independent) | ja | 33 | 0.061 -> 0.879 (+0.818) | 0.061 -> 0.781 (+0.721) |
| 160 | claude-fable-5.1 (independent) | zh | 45 | 0.000 -> 0.889 (+0.889) | 0.000 -> 0.822 (+0.822) |
| 160 | claude-fable-5.1 (independent) | es | 36 | 0.806 -> 0.833 (+0.028) | 0.636 -> 0.775 (+0.139) |
| 160 | claude-fable-5.1 (independent) | de | 45 | 0.778 -> 0.844 (+0.067) | 0.614 -> 0.762 (+0.148) |
| 1000 | all three authors | en | 252 | 0.635 -> 0.679 (+0.044) | 0.529 -> 0.581 (+0.053) |
| 1000 | all three authors | ko | 243 | 0.613 -> 0.613 (+0.000) | 0.557 -> 0.552 (-0.004) |
| 1000 | all three authors | ja | 99 | 0.061 -> 0.848 (+0.788) | 0.061 -> 0.782 (+0.722) |
| 1000 | all three authors | zh | 135 | 0.000 -> 0.830 (+0.830) | 0.000 -> 0.766 (+0.766) |
| 1000 | all three authors | es | 108 | 0.648 -> 0.694 (+0.046) | 0.593 -> 0.655 (+0.062) |
| 1000 | all three authors | de | 135 | 0.674 -> 0.748 (+0.074) | 0.579 -> 0.666 (+0.087) |
| 1000 | gpt-6.1-sol (independent) | en | 84 | 0.512 -> 0.583 (+0.071) | 0.441 -> 0.512 (+0.071) |
| 1000 | gpt-6.1-sol (independent) | ko | 81 | 0.667 -> 0.667 (+0.000) | 0.596 -> 0.605 (+0.010) |
| 1000 | gpt-6.1-sol (independent) | ja | 33 | 0.061 -> 0.879 (+0.818) | 0.061 -> 0.821 (+0.760) |
| 1000 | gpt-6.1-sol (independent) | zh | 45 | 0.000 -> 0.822 (+0.822) | 0.000 -> 0.762 (+0.762) |
| 1000 | gpt-6.1-sol (independent) | es | 36 | 0.583 -> 0.667 (+0.083) | 0.459 -> 0.577 (+0.118) |
| 1000 | gpt-6.1-sol (independent) | de | 45 | 0.644 -> 0.667 (+0.022) | 0.511 -> 0.599 (+0.088) |
| 1000 | claude-fable-5.1 (independent) | en | 84 | 0.714 -> 0.750 (+0.036) | 0.574 -> 0.641 (+0.066) |
| 1000 | claude-fable-5.1 (independent) | ko | 81 | 0.531 -> 0.556 (+0.025) | 0.490 -> 0.487 (-0.004) |
| 1000 | claude-fable-5.1 (independent) | ja | 33 | 0.061 -> 0.818 (+0.758) | 0.061 -> 0.742 (+0.682) |
| 1000 | claude-fable-5.1 (independent) | zh | 45 | 0.000 -> 0.867 (+0.867) | 0.000 -> 0.785 (+0.785) |
| 1000 | claude-fable-5.1 (independent) | es | 36 | 0.694 -> 0.750 (+0.056) | 0.662 -> 0.736 (+0.074) |
| 1000 | claude-fable-5.1 (independent) | de | 45 | 0.667 -> 0.844 (+0.178) | 0.564 -> 0.729 (+0.165) |

#### Index cache on disk (all sidecar files after build + all queries)

| engine | notes | main | this change |
|---|---|---|---|
| birkin | 160 | 0.32 MB | 0.08 MB |
| birkin | 1000 | 1.87 MB | 0.40 MB |
| bundled | 160 | 0.17 MB | 0.07 MB |
| bundled | 1000 | 0.97 MB | 0.35 MB |


#### Build time and query latency (one run each, Python 3.13, on a machine shared with other jobs; indicative only)

| engine | notes | full index build | p50 query |
|---|---|---|---|
| birkin | 160 | 0.13 s -> 0.09 s | 2.0 ms -> 2.0 ms |
| birkin | 1000 | 0.55 s -> 0.46 s | 15.2 ms -> 11.8 ms |
| bundled | 160 | 0.06 s -> 0.08 s | 2.0 ms -> 2.2 ms |
| bundled | 1000 | 0.32 s -> 0.46 s | 10.2 ms -> 12.4 ms |

#### Reading

- **`birkin.mnemosyne`** already indexed Hangul, Han and kana, so Japanese and
  Chinese do not move: not one of their 234 test questions changes rank at
  either size. What changes is everything alphabetic. `main` cut words at
  every non-ASCII letter (`azafrán` -> `azafr`, `n`), so an unaccented query
  (`azafran`), a full-width one (`ＡＰＩ`), or any Cyrillic or Greek word found
  nothing; those now match. German, Spanish and English improve.
- **Not every slice is at least as good as before.** Korean: 1 of 243 test
  questions drops one rank at 160 notes (8th -> 9th) and 2 at 1000 notes
  (3rd -> 4th, 1st -> 2nd); none moves up. All three are questions from the
  `claude-fable-5.1` set. The cause is corpus-wide: once Spanish and German
  notes stop splitting into fragments, document frequencies and the average
  document length change for every note, and near-ties flip. Spanish gains
  first places (+6/-2 at 160 notes, +7/-1 at 1000) but has fewer questions in
  the top five (+2/-4 at 160 notes, +1/-2 at 1000): truncation stems pull in
  a few unrelated notes for paraphrase questions.
- **Known follow-up.** The Korean result is accepted as it stands for this
  change and is to be fixed in birkin-mnemosyne, not here: on the engine
  behind `memory_search`, 1 of 243 Korean test questions drops one rank at
  160 notes and 2 at 1000 notes, and none improves.
- **Three choices are specific to `birkin.mnemosyne`** and its query-side idf
  weight (ADR-043), each taken on the dev split:
  1. Stems stay out of the document length, so a query that uses no stem sees
     the same length normalisation as before.
  2. In a query that holds a Hangul, Han or kana term, stems are used only
     when it holds a single alphabetic word (a Korean question quoting one
     English term). With several English words, each would score twice (word
     + stem) against English notes and outrank the note written in the other
     language. The first, unadapted port lost Korean -0.010, Chinese -0.017
     and Japanese -0.005 MRR at 160 notes.
  3. The English possessive `'s` is dropped. `main` hid the problem by
     accident: the stray `s` fragments of accented words made `s` a common
     term. With those gone, a lone `s` is rare and heavily weighted, and
     "Nana's" matched any question containing a possessive.
  Stems, through 1 and 2, were the whole of that loss: with stems switched
  off those three languages did not move. The script bonus changes 1 of 1440
  top-ten lists in this engine at either size; it is kept for parity with the
  bundled package.
- **Bundled `birkin_mnemosyne`** is upstream 0.4.0's lexical core unchanged
  and reproduces upstream's published numbers, including its known Korean
  dip (-0.004 MRR at 160 notes, 12 questions up and 15 down). It was blind
  to Japanese and Chinese before. It is not on Birkin's recall path; only
  `birkin/profile_review.py` imports the package.
- **Index cache.** The file is compact UTF-8 JSON compressed with zlib level
  1. At 1000 notes the `birkin.mnemosyne` cache is 396,914 bytes against
  1,948,530 bytes for the same content as plain JSON (20%); at 160 notes
  83,142 against 339,541 (24%). An engine that loads the compressed cache
  without re-parsing a note returns the same top ten as the engine that built
  it for all 1440 questions, at both sizes and in both engines.
- **Not ported:** upstream's optional semantic mode (static embeddings, a
  one-time ~530 MB model download). Upstream measured it slightly worse on
  some Chinese slices. Birkin's own opt-in vector signal
  (`memory_vector_enabled`, extra `memory-semantic`) is unchanged and off by
  default.
