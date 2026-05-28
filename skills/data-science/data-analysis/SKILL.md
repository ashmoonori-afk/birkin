---
name: data-analysis
description: "Explore a dataset, compute summary stats, surface insights via run_shell."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [data-science, analysis, insights]
---

# Data Analysis

Load and explore a dataset, compute summary statistics, identify patterns,
and surface actionable insights using shell-based data tools (awk, grep, Python).

## When to Use

- You have a local dataset (CSV, JSON, log file) to analyze.
- You need to summarize, filter, or compute aggregates.
- You need to identify outliers, trends, or correlations.

## When NOT to Use

- The data is very large (>1 GB) and requires a data warehouse.
- The analysis requires machine learning or complex statistical modeling.
- The data source is a remote API or database not accessible locally.

## Procedure

1. Use `list_files` to locate the dataset.
2. Use `read_file` to inspect structure (first 20 lines, data types, column names).
3. Use `run_shell` to compute summary stats:
   - Row count, column count, missing values
   - Min, max, mean, median, standard deviation (for numeric columns)
   - Unique value counts (for categorical columns)
4. Identify patterns:
   - Filter or group by key dimensions (e.g., by region, time period).
   - Look for outliers or anomalies.
   - Calculate trends (e.g., growth, decline) over time if applicable.
5. Generate visualizable output (counts, distributions, top-N lists).
6. Synthesize insights:
   - What is surprising or noteworthy?
   - What decisions or actions does this enable?
7. Save analysis results (summary stats, key findings) to memory with
   `memory_write_note`.

## Output

- Summary statistics (count, missing, min, max, mean, median, std).
- Top findings (bullets, with supporting numbers).
- Suggested next steps (deeper analysis, data validation, decision implications).
- Shell commands used (for reproducibility).
