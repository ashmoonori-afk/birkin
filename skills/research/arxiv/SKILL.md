---
name: arxiv
description: "Search arXiv papers by keyword, author, category, or ID (bundled script)."
version: 1.0.0
author: birkin (ported from hermes-agent, MIT)
license: MIT
metadata:
  birkin:
    tags: [research, arxiv, papers, academic]
---

# arXiv Search

Search academic papers on arXiv. This skill **bundles an executable script**
(`scripts/search_arxiv.py`, standard library only) — a working example of a
hermes/openclaw-style skill that ships code, not just instructions.

## When to Use

- The user asks for academic papers, recent research, or a specific arXiv ID.
- You need authors, abstracts, categories, or PDF links for papers.

## When NOT to Use

- General web questions (use `web-research`).
- Non-academic sources.

## Procedure

1. Run the bundled script with `run_shell`, setting `cwd` to **this skill's
   directory** (shown under "Bundled files" when you load this skill):
   ```
   python scripts/search_arxiv.py "your topic" --sort date --max 10
   python scripts/search_arxiv.py --author "Yann LeCun" --max 5
   python scripts/search_arxiv.py --category cs.AI --sort date
   python scripts/search_arxiv.py --id 2402.03300
   ```
2. Read the printed results (title, authors, abstract, categories, links).
3. Synthesize a sourced summary; cite each paper by its arXiv ID and link.
4. If the findings are durable, save them with `memory_write_note`.

## Output

- A concise, sourced summary of the most relevant papers, each with its arXiv
  ID and links. Never fabricate results — only report what the script returned.
