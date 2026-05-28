---
name: csv-wrangling
description: "Clean, transform, join CSVs with run_shell and scripts."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [data-science, data-cleaning, csv]
---

# CSV Wrangling

Clean, transform, and join CSV files using shell commands and scripts. Handle
missing values, format inconsistencies, duplicates, and multi-file merges.

## When to Use

- Raw CSV data needs cleaning (duplicates, missing values, format issues).
- Multiple CSVs must be combined or joined on a key.
- Data must be pivoted, filtered, or reformatted before analysis or loading.

## When NOT to Use

- Data is already clean and ready for use.
- The dataset is very large (>1 GB) and requires a data warehouse.
- Complex transformations require a full ETL pipeline.

## Procedure

1. Use `read_file` to inspect the CSV structure, headers, and sample rows.
2. Identify issues: missing values, duplicates, inconsistent types, encoding,
   whitespace.
3. Write a shell script (using awk, sed, cut, sort, uniq) or Python script to:
   - Remove or fill missing values
   - Deduplicate rows (by key or entirely)
   - Standardize formats (dates, numbers, strings)
   - Rename or reorder columns
   - Filter rows (e.g., by date range or criteria)
4. For multi-file operations:
   - Join CSVs on a common key (using awk, join, or Python)
   - Concatenate rows (with header handling)
5. Use `run_shell` to execute the script and validate output (sample rows, row count).
6. Save the cleaned/transformed CSV with a descriptive name.
7. Document the transformation in memory with `memory_write_note` (source,
   transformations applied, any data loss or decisions made).

## Output

- A clean, transformed CSV file ready for analysis.
- A script or set of shell commands (for reproducibility and re-running).
- Summary of changes (rows removed, values standardized, columns added/removed).
- Any data quality decisions or assumptions documented.
