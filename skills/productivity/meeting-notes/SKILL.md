---
name: meeting-notes
description: "Convert raw meeting notes into decisions, actions, and owners."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [productivity, notes, meetings]
---

# Meeting Notes

Extract structured outcomes from raw meeting notes: what was decided, what actions
follow, and who owns each one. Makes notes actionable and searchable.

## When to Use

- User has raw meeting notes (voice-to-text, scribbles, shared doc).
- User wants clarity on decisions and next steps.
- Need to distribute action items to a team.

## When NOT to Use

- Notes are already structured.
- The meeting had no decisions or actions.

## Procedure

1. Read the raw notes (`read_file` if in a file, or accept pasted text).
2. Identify and extract:
   - **Attendees**: who was there.
   - **Decisions**: what was agreed upon (explicit or implicit).
   - **Actions**: what needs to happen; reference the decision it comes from.
   - **Owners**: who will do it; confirm with them if unclear.
   - **Due dates**: when; default to next business day if unspecified.
3. Use `memory_write_note` to store decisions for future reference.
4. Validate that each action has an owner and due date.
5. Output as a structured document with sections.

## Output

```
# <Meeting Name> — <date>
Attendees: …
Decisions: 1) … 2) …
Action Items:
  - [ ] <action> (Owner: <name>, Due: <date>)
  - [ ] <action> (Owner: <name>, Due: <date>)
```
