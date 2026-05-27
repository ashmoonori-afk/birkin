---
name: web-scraping
description: "Extract structured data from web pages with web_fetch, respecting ToS."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [automation, scraping, data]
---

# Web Scraping

Harvest structured data from web pages: product listings, prices, articles, etc.
Use `web_fetch` to retrieve HTML; parse and validate before storage.

## When to Use

- Need to collect data from a public web source.
- Building a dataset for analysis or integration.
- Monitoring prices, news, or availability.

## When NOT to Use

- The site has an API (use it instead).
- robots.txt or Terms of Service forbid scraping.
- Data is behind authentication without explicit permission.

## Procedure

1. Check the site's robots.txt and Terms of Service for scraping restrictions.
2. Clarify the data needed: what fields, how many records, refresh frequency.
3. Use `web_fetch` to download the HTML page.
4. Parse the HTML to extract data:
   - Identify CSS selectors or patterns for the target elements.
   - Handle pagination if multiple pages exist.
   - Extract fields: title, price, URL, date, etc.
5. Validate data quality: check for missing fields, outliers, duplicates.
6. Store or export: CSV, JSON, or database.
7. If scraping is repeated, use `run_shell` to script it with rate limiting.

## Output

```
Source: <URL>
Data extracted: <count> records
Fields: <field1, field2, …>
Sample:
  - <record1>
  - <record2>
Export: <path> (CSV|JSON)
```
