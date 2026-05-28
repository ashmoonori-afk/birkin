---
name: blog-post
description: "Draft engaging, well-structured blog posts from outline or topic."
version: 1.0.0
author: birkin
license: Proprietary
metadata:
  birkin:
    tags: [writing, content, blog]
---

# Blog Post

Transform an outline, topic, or raw notes into a finished blog post that engages
readers, delivers value, and encourages sharing or action.

## When to Use

- You have an outline and need a polished first draft.
- Topic is assigned and you need to structure it into a readable post.
- Want to repurpose existing notes, research, or talk transcripts into a post.

## When NOT to Use

- Ultra-short posts or social updates (use email-draft for brevity patterns).
- Technical documentation (use technical-writing skill).
- Need a finished, SEO-optimized post (this skill produces a draft).

## Procedure

1. Clarify the **core point** in one sentence and the **target reader**.
2. Build an outline: hook → context → key insights → takeaway → CTA.
3. Draft the opening paragraph to hook attention; explain the problem or promise.
4. Write each section in 150–300 words; support claims with examples or data.
5. Include one narrative example, case study, or analogy readers will remember.
6. Close with a clear lesson and next action (comment, share, implement, etc.).
7. Call `write_file` to save as post.md or blog-post.md.

## Output

- Markdown file (.md) with headline, sections, examples, and CTA.
- Estimated length: 1000–2500 words.
- Tone: conversational, clear, authoritative; avoid marketing speak.
