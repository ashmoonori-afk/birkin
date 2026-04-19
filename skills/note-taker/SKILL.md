---
name: note-taker
description: Structure raw notes into organized wiki-format markdown
version: "1.0"
triggers:
  - organize notes
  - take notes
  - 노트 정리
  - 메모 정리
tools: []
---

## Instructions

When the user provides raw notes or asks to organize information, transform it
into clean, structured markdown. Follow these steps:

1. **Understand the source** — The input may be:
   - Stream-of-consciousness text
   - Meeting transcripts or voice memo dumps
   - Bullet-point fragments
   - Copy-pasted research snippets
   - Mixed Korean/English content

2. **Identify structure** — Read through the entire input first. Look for:
   - Main topics and subtopics
   - Action items or decisions
   - Questions that remain unanswered
   - Key facts, dates, names, or numbers
   - Relationships between ideas

3. **Organize into sections** — Apply this template (adapt sections as needed):

```markdown
# <Title — infer from content>

## Summary
<2-3 sentence overview of the notes>

## Key Points
- <main insight 1>
- <main insight 2>
- <main insight 3>

## Details

### <Topic A>
<organized content>

### <Topic B>
<organized content>

## Action Items
- [ ] <task 1> — <owner if mentioned> — <deadline if mentioned>
- [ ] <task 2>

## Open Questions
- <question 1>
- <question 2>

## References
- <any links, names, or sources mentioned>
```

4. **Processing rules**:
   - Remove redundancy. Merge duplicate points.
   - Fix obvious typos and grammar issues, but preserve the author's voice.
   - Convert vague statements into concrete ones where possible.
   - Add context markers like `[needs confirmation]` or `[unclear]` for
     ambiguous content rather than guessing.
   - Keep the original language. If notes are in Korean, output in Korean.

5. **Wiki-linking** — If the notes reference concepts, people, or projects that
   could be separate wiki pages, use `[[double bracket]]` notation to mark them
   as potential links.

6. **Tags** — Add relevant tags at the bottom of the note:
   ```
   Tags: #topic1 #topic2 #topic3
   ```

7. **Follow-up** — After organizing, ask the user if they want to:
   - Save the note to a specific location
   - Extract action items as a separate checklist
   - Expand any section with more detail
