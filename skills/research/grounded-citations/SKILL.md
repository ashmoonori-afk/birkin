---
name: grounded-citations
description: "Verify every claim against the source text with verify_citations before presenting a cited answer; drop or re-source anything unsupported."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [research, verification, citations, fact-check]
---

# Grounded Citations

Do not present a cited answer until each claim has been checked against the
text of the source cited for it.

This is not the same as `fact-checking`, which decides whether a claim is
*true* by consulting authorities. This decides whether **your citation supports
the sentence you attached it to** — a different failure, and the more common
one: a model asked to cite will produce a plausible URL for a sentence that URL
never states, and no amount of care in the writing detects it.

## When to Use

- You are about to answer with claims that carry citations.
- You are writing a research report, a summary of fetched pages, or a
  fact-check verdict.
- A claim came from a page you skimmed rather than read closely.

## When NOT to Use

- The answer cites nothing.
- The claims are the user's own, restated back to them.
- You are reasoning about code or files in the workspace rather than sources.

## Procedure

1. `web_fetch` every source you intend to cite. Keep the text as returned —
   the check is against what the page says, not against your summary of it.
2. Write out each factual claim as one standalone sentence, carrying its own
   numbers and dates. "It closes in September" cannot be verified; "Submissions
   close on 30 September 2026" can.
3. Call `verify_citations` with those claims and `{url, text}` for each fetched
   source.
4. For every claim reported UNSUPPORTED: fetch a source that does state it, or
   remove the claim. Do not reword the claim to make the check pass — that
   changes what you are asserting, not what the source says.
5. Present the answer, citing the URL the tool matched for each claim.

## Output

State the verified claims with their sources. If any claim was dropped for
lack of support, say so — a gap the user knows about is worth more than a
confident sentence with a citation that does not hold.

## Notes

The check is lexical: it looks for a sentence carrying the claim's content
words and agreeing on its numbers. A claim supported only by paraphrase can
come back UNSUPPORTED even though the source does back it. That direction is
cheap — read the quoted sentence and decide for yourself. The opposite error
is not: a citation that "passes" while saying nothing of the kind is exactly
what this exists to prevent.
