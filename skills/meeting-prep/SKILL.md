---
name: meeting-prep
description: Prepare meeting agendas, research attendees, and generate talking points
version: "1.0"
triggers:
  - meeting prep
  - prepare meeting
  - 미팅 준비
  - 회의 준비
tools: []
---

## Instructions

When the user asks to prepare for a meeting, help them walk in fully prepared.
Follow these steps:

1. **Gather meeting context** — Ask for or identify:
   - Meeting purpose (pitch, status update, brainstorm, negotiation, 1-on-1)
   - Attendees (names, roles, companies)
   - Date and time
   - Duration
   - Any existing agenda or pre-read materials
   - User's goals for this specific meeting

2. **Research attendees** — For each attendee (if information is available):
   - Role and responsibilities
   - Recent relevant activity (projects, publications, social media)
   - Shared history or past interactions with the user
   - Communication style notes (detail-oriented, big-picture, etc.)

   Format as a quick reference card per person:
   ```
   ### <Name> — <Role, Company>
   - Background: ...
   - Recent activity: ...
   - Note: ...
   ```

3. **Build the agenda** — Structure the meeting time:

```markdown
## Meeting Agenda — <Topic>
**Date:** YYYY-MM-DD HH:MM
**Duration:** X minutes
**Attendees:** ...

| Time | Topic | Owner | Goal |
|------|-------|-------|------|
| 0:00 | Opening & context | <user> | Align on purpose |
| 0:05 | <topic 1> | ... | <desired outcome> |
| 0:15 | <topic 2> | ... | <desired outcome> |
| ... | ... | ... | ... |
| X:XX | Next steps & close | <user> | Clear action items |
```

4. **Generate talking points** — For each agenda item, prepare:
   - 2-3 key points to make
   - Supporting data or examples
   - Potential questions from attendees and prepared responses
   - Transition sentences to the next topic

5. **Anticipate objections** — Based on the meeting type:
   - **Pitch**: Common pushback and counter-arguments
   - **Negotiation**: Likely positions and fallback options
   - **Status update**: Tough questions about delays or issues
   - **Brainstorm**: Ways to keep discussion productive

6. **Prepare materials checklist**:
   - [ ] Slides or deck (if needed)
   - [ ] Data or metrics to reference
   - [ ] Printed agendas or shared doc link
   - [ ] Demo environment (if applicable)
   - [ ] Backup plan if tech fails

7. **Post-meeting template** — Include a template for meeting notes:

```markdown
## Meeting Notes — <Topic> — YYYY-MM-DD

### Decisions Made
- ...

### Action Items
- [ ] <task> — <owner> — <deadline>

### Key Discussion Points
- ...

### Follow-ups
- ...
```

8. **Language** — Respond in the same language as the user's request. Korean
   meetings get Korean agendas with appropriate business formality levels.
