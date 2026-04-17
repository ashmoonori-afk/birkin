---
name: web-summarizer
description: Summarize web pages and articles into concise bullet points
version: "0.3.0"
triggers:
  - summarize
  - summary
  - tldr
tools:
  - summarize_text
---

## Instructions

When the user asks for a summary, use the `summarize_text` tool.
Extract the key points and present them as concise bullet points.
Aim for 3-7 bullet points that capture the essence of the content.
