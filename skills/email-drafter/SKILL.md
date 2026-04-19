---
name: email-drafter
description: Draft professional emails from context and intent
version: "1.0"
triggers:
  - draft email
  - write email
  - 이메일 작성
  - 메일 초안
tools: []
---

## Instructions

When the user asks to draft an email, follow these steps:

1. **Gather context** — Before writing, confirm you have:
   - Recipient (who is this going to?)
   - Purpose (request, follow-up, introduction, apology, announcement, etc.)
   - Key points the user wants to convey
   - Tone preference (formal, friendly, urgent, diplomatic)
   - Any constraints (word limit, language, deadline mention)

   If any critical context is missing, ask the user before drafting.

2. **Structure the email** — Use a clear layout:
   - **Subject line** — Short, specific, action-oriented. Never generic.
   - **Opening** — One sentence establishing context or greeting.
   - **Body** — Organized paragraphs, each covering one point. Use bullet
     points when listing multiple items.
   - **Call to action** — Clearly state what you need from the recipient
     and by when.
   - **Closing** — Appropriate sign-off matching the tone.

3. **Writing rules**:
   - Keep sentences short. Aim for 15-20 words per sentence.
   - One idea per paragraph.
   - Avoid filler phrases ("I hope this email finds you well", "Just wanted to
     reach out", "Per my last email").
   - Be direct about requests. State what you need, not what you wish.
   - Use active voice.
   - Match formality to the relationship (colleague vs. client vs. executive).

4. **Multi-language support**:
   - If the user requests in Korean, draft the email in Korean with appropriate
     honorifics and business Korean conventions.
   - For English emails to Korean recipients, note cultural context where
     relevant (e.g., appropriate level of directness).

5. **Output format**:

```
**Subject:** <subject line>

---

<email body>

---

**Notes:** <any suggestions for timing, follow-up, or attachments>
```

6. **Variations** — If the user seems uncertain about tone, offer two versions:
   one more formal and one more conversational, and let them choose.
