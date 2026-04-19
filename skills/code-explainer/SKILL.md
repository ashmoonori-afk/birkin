---
name: code-explainer
description: Explain code with step-by-step breakdown and examples
version: "1.0"
triggers:
  - explain code
  - what does this code do
  - 코드 설명
  - 이 코드 뭐야
tools: []
---

## Instructions

When the user asks to explain code, provide a clear, layered explanation that
builds understanding from high-level to low-level. Follow these steps:

1. **One-line summary** — Start with a single sentence describing what the code
   does in plain language. No jargon.

2. **High-level overview** — Explain the purpose and context:
   - What problem does this code solve?
   - Where would this typically be used?
   - What are the inputs and outputs?

3. **Step-by-step walkthrough** — Go through the code section by section:
   - Number each step.
   - Quote the relevant line(s) of code.
   - Explain what that section does and why.
   - Call out any non-obvious behavior (implicit type coercion, side effects,
     closure captures, etc.).

   Format:
   ```
   **Step 1:** `line_of_code_here`
   This does X because Y. The result is stored in Z.
   ```

4. **Key concepts** — If the code uses patterns or concepts that may not be
   familiar, explain them briefly:
   - Design patterns (Observer, Factory, etc.)
   - Language-specific idioms (list comprehensions, decorators, async/await)
   - Algorithms or data structures

5. **Example usage** — Provide a concrete example of how to call/use the code
   with sample inputs and expected outputs:
   ```
   # Example
   result = function_name(sample_input)
   # result => expected_output
   ```

6. **Potential issues** — Note any concerns:
   - Edge cases not handled
   - Performance implications
   - Security considerations
   - Common mistakes when using this code

7. **Adaptation rules**:
   - **Audience level**: If the user seems like a beginner (asks "what is X?"),
     explain foundational concepts. If they seem experienced (asks about
     specific behavior), skip basics and focus on nuances.
   - **Language**: Respond in the same language the user used. Korean question
     gets a Korean explanation.
   - **Scope**: If the user points to a specific line, focus the explanation
     there. If they share an entire file, cover the overall architecture first,
     then drill into important functions.

8. **Visual aids** — When helpful, use:
   - ASCII diagrams for data flow
   - Tables for comparing values across steps
   - Indented call trees for nested function calls
