# Semantic memory / LongMemEval results

## Published fixture run

These numbers are **fixture-based**, not public LongMemEval leaderboard results. The host did not have the public dataset available, so this run uses the committed 14-question mini set (`2 x 7` required categories), deterministic local hash embeddings, and a deterministic reader that extracts an `Answer:` line from the assembled top-1 snippet. Retrieval recall is measured at 5; answer accuracy is measured after top-1 context assembly. The deliberate difference makes the retrieval-versus-reading bottleneck measurable instead of conflating the stages.

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

## Full public LongMemEval

Install the optional **local** vector backend and obtain `longmemeval_s_cleaned.json` from the public LongMemEval release. Core Birkin and lexical-only runs do not need the extra.

```powershell
python -m pip install -e ".[memory-semantic]"
$env:PYTHONUTF8=1
$env:PYTHONIOENCODING='utf-8'
python benchmarks/bench_memory_longmemeval.py `
  --data C:\datasets\LongMemEval\longmemeval_s_cleaned.json `
  --vector-backend all-MiniLM-L6-v2 `
  --answer-command "C:\path\to\local-json-answerer.exe" `
  --out benchmarks/results/memory-longmemeval-public.json
```

`--answer-command` must read one JSON object (`{"question": ..., "context": ...}`) from stdin and print only its answer. This supports Ollama, llama.cpp, or another fully local reader through a small adapter. Omitting it selects the deterministic `Answer:`-line fixture reader, which is useful for the committed fixture but is not a meaningful public-dataset reader. The output JSON contains every category, both stage metrics, and all cost fields for every configuration.
