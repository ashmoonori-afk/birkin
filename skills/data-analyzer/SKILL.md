---
name: data-analyzer
description: Analyze CSV/JSON data with summary stats and insights
version: "1.0"
triggers:
  - analyze data
  - data summary
  - 데이터 분석
  - 통계
tools: []
---

## Instructions

When the user provides data (CSV, JSON, or tabular text) for analysis, follow
this workflow:

1. **Inspect the data** — Before any analysis, understand what you have:
   - Number of rows and columns
   - Column names and inferred data types
   - Sample of first few rows
   - Identify if it is time-series, categorical, transactional, etc.

   Report this overview first so the user can confirm the data looks correct.

2. **Data quality check**:
   - Missing values: count per column, percentage
   - Duplicates: count of duplicate rows
   - Outliers: flag values that are statistically unusual (>3 standard
     deviations from mean for numeric columns)
   - Data type issues: numbers stored as strings, inconsistent date formats

3. **Summary statistics** — For each numeric column:
   - Count, mean, median, standard deviation
   - Min, max, 25th/75th percentiles
   - Skewness direction (left/right/symmetric)

   For categorical columns:
   - Unique value count
   - Top 5 most frequent values with counts
   - Distribution shape (uniform, power-law, etc.)

4. **Key insights** — Go beyond raw stats. Look for:
   - Trends: Is there a clear upward/downward pattern over time?
   - Correlations: Which columns move together?
   - Segments: Are there natural groupings in the data?
   - Anomalies: Specific rows or periods that stand out
   - Concentration: Is the data dominated by a few values/categories?

   Present each insight as:
   ```
   **Insight:** <what you found>
   **Evidence:** <supporting numbers>
   **Implication:** <what this means for the user>
   ```

5. **Visualization suggestions** — Recommend specific chart types:
   - Time trends: line chart
   - Distributions: histogram or box plot
   - Comparisons: bar chart
   - Relationships: scatter plot
   - Composition: pie chart or stacked bar
   - If the user has matplotlib/plotly available, offer to generate the code.

6. **Output format**:

```markdown
## Data Overview
- Rows: X | Columns: Y
- Date range: (if applicable)
- Key columns: ...

## Data Quality
| Column | Missing | Type | Notes |
|--------|---------|------|-------|
| ...    | ...     | ...  | ...   |

## Summary Statistics
<tables>

## Key Insights
1. ...
2. ...
3. ...

## Recommended Next Steps
- <suggestion 1>
- <suggestion 2>
```

7. **Language** — Use the same language as the user's request. If asked in
   Korean, produce the entire analysis in Korean.

8. **Follow-up** — After the initial analysis, ask if the user wants to:
   - Drill into a specific column or segment
   - Compare groups or time periods
   - Export a cleaned version of the data
   - Generate visualization code
