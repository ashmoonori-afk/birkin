---
name: competitive-analysis
description: "Compare products/competitors across feature, price, positioning."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [research, competitive, market]
---

# Competitive Analysis

Compare a set of products, companies, or offerings across structured dimensions
(features, pricing, positioning, market share, user experience) to identify
strengths, weaknesses, and differentiation opportunities.

## When to Use

- You need to position a product or service relative to alternatives.
- The user is evaluating which option to choose or recommend.
- You need market insights for strategy or product planning.

## When NOT to Use

- The analysis requires proprietary or non-public financial data.
- There are fewer than 2 comparable competitors or offerings.
- The decision is already made or the analysis is purely historical.

## Procedure

1. Define the competitive set: identify 3–5 direct or close competitors.
2. Choose 5–8 comparison dimensions (e.g., core features, pricing model, target
   audience, ease of use, support, integrations, security).
3. For each competitor, use `web_fetch` to gather information from:
   - Official product pages and pricing
   - User reviews (G2, Capterra, product-specific sites)
   - Press releases and positioning statements
   - Technical documentation
4. Populate a comparison matrix (features, pricing, strengths, weaknesses).
5. Synthesize findings:
   - **Market Overview** (size, growth, key players)
   - **Comparison Matrix** (structured table or narrative)
   - **Positioning Map** (where each competitor sits on key dimensions)
   - **Strengths & Weaknesses** (for each player)
   - **White Spaces** (underserved needs or segments)
6. Save analysis to memory with `memory_write_note` and timestamp.

## Output

- A comparison matrix or table (visual or text).
- Narrative analysis of positioning, differentiation, and market gaps.
- Actionable recommendations (e.g., areas to exploit, features to prioritize).
- All sources cited with URLs.
