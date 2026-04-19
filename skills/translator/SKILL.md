---
name: translator
description: Translate text with context preservation, supports KO/EN/JP/ZH
version: "1.0"
triggers:
  - translate
  - translation
  - 번역
  - 翻訳
tools: []
---

## Instructions

When the user asks for a translation, follow these guidelines:

1. **Detect languages** — Identify the source language automatically. If the
   target language is not specified, infer it:
   - If source is Korean, default target is English.
   - If source is English, default target is Korean.
   - For Japanese or Chinese source, ask the user for the target language.
   - If the user specifies a target language explicitly, always use that.

2. **Translation principles**:
   - **Meaning over words** — Translate the intent, not word-by-word. Preserve
     the original meaning, tone, and nuance.
   - **Context preservation** — Technical terms should be translated accurately
     within their domain context. If a term is commonly kept in English even in
     Korean text (e.g., API, commit, deploy), keep it.
   - **Register matching** — Match the formality level of the original. Casual
     text stays casual; formal text stays formal.
   - **Cultural adaptation** — Adjust idioms, metaphors, and cultural
     references so they make sense in the target language. Do not translate
     idioms literally.

3. **Supported language pairs**:
   - Korean (KO) <-> English (EN)
   - Korean (KO) <-> Japanese (JP)
   - Korean (KO) <-> Chinese (ZH)
   - English (EN) <-> Japanese (JP)
   - English (EN) <-> Chinese (ZH)
   - Japanese (JP) <-> Chinese (ZH)

4. **Output format**:

```
**Source (XX):**
<original text>

**Translation (XX):**
<translated text>

**Notes:**
- <any terms that have multiple valid translations, with alternatives>
- <cultural context notes if relevant>
```

5. **Special cases**:
   - **Code comments/docs**: Translate comments and documentation strings but
     keep code identifiers (variable names, function names) unchanged.
   - **Mixed-language text**: Translate only the portions in the source language;
     keep the rest as-is.
   - **Ambiguous terms**: When a term has multiple valid translations, provide
     the best fit and note alternatives.

6. **Batch translation** — If the user provides multiple paragraphs or items,
   translate each one separately and maintain the original structure (headings,
   bullet points, numbering).

7. **Review request** — If the user provides an existing translation and asks
   for review, compare it against the source and suggest corrections with
   explanations for each change.
