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
