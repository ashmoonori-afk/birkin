---
name: prompt-engineering
description: "Design effective prompts: role, context, constraints, examples, feedback loop."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [knowledge, prompts, ai, engineering]
---

# Prompt Engineering

Craft prompts that guide language models toward reliable, high-quality outputs by establishing role, context, constraints, and examples.

## When to Use

- An LLM task is returning off-target or inconsistent results.
- You need to optimize a recurring prompt for production use.
- Teaching another person how to get better results from an AI tool.

## When NOT to Use

- One-off exploratory queries; prompt engineering is for repeated or critical tasks.
- Tasks that require reasoning or research; use extended thinking or agent skills instead.

## Core Components

A strong prompt includes:

1. **Role**: "You are a [specific expertise/persona]."
2. **Context**: "I am [your situation]. I need [specific outcome]."
3. **Constraints**: "Keep it under 100 words." "Use only [specific data]." "No fabricated examples."
4. **Examples**: Show what good looks like (few-shot prompting).
5. **Output format**: "Return as JSON/markdown/bullet list."
6. **Feedback loop**: Test → observe → refine.

## Procedure

1. Define your role and desired output type clearly.
2. Write a baseline prompt; test with 3–5 examples.
3. Observe patterns in failures or mediocre outputs.
4. Refine: add examples, tighten constraints, reorder instructions.
5. Test iteratively; track what works and what doesn't in `memory_write_note`.
6. Lock in the final prompt version.

## Output

- Final prompt text (copy-paste ready).
- Test results: input, output, quality assessment.
- Refinement history (what changed and why).
- Known limitations or edge cases.
