---
name: daily-digest
description: Summarize top HackerNews stories into a daily briefing
version: "1.0"
triggers:
  - daily digest
  - news summary
  - morning briefing
  - 오늘 뉴스
  - HN 요약
tools: []
---

## Instructions

When the user requests a daily digest or news summary, produce a concise briefing
of the top stories from HackerNews (or a similar tech news source if HN is
unavailable). Follow these steps:

1. **Fetch stories** — Retrieve the current top 10-15 stories from
   HackerNews using the public API (`https://hacker-news.firebaseio.com/v0/`).
   If web access is not available, ask the user to paste the stories or provide
   a URL.

2. **Categorize** — Group stories into sections:
   - Tech & Engineering
   - AI & ML
   - Startups & Business
   - Science & Research
   - Culture & Other

3. **Summarize each story** — For every story provide:
   - One-line headline with the original link
   - 2-3 sentence summary of why it matters
   - Comment count and score when available

4. **Daily highlight** — Pick the single most impactful story and write a
   short paragraph (3-5 sentences) explaining its significance.

5. **Format** — Use this structure:

```markdown
# Daily Digest — YYYY-MM-DD

## Highlight of the Day
<paragraph>

## Tech & Engineering
- **<title>** (<score> pts, <comments> comments)
  <summary>

## AI & ML
...

## Quick Links
- <remaining lower-priority stories as bullet links>
```

6. **Tone** — Professional but approachable. Avoid hype language. Prioritize
   clarity and relevance to a technical audience.

7. **Language** — Default to the language the user used in their request.
   If the user writes in Korean, produce the entire briefing in Korean.
