# Skill Authoring Guide

This guide explains how to create, test, and publish community skills for Birkin.

## What is a Birkin Skill?

A skill is a self-contained capability packaged as a directory. Each skill contains:

- **SKILL.md** (required) — metadata in YAML frontmatter plus instructions in the body
- **tool.py** (optional) — Python tool implementations that the agent can invoke
- **resources/** (optional) — static files (prompts, templates, data)

## Directory Structure

```
my-skill/
  SKILL.md          # Required: metadata + instructions
  tool.py           # Optional: Tool subclass implementations
  resources/        # Optional: static resources
    prompt.txt
```

## SKILL.md Format

The file must start with YAML frontmatter between `---` fences, followed by Markdown instructions.

```markdown
---
name: my-skill
description: Short description of what this skill does
version: "1.0.0"
triggers:
  - keyword1
  - keyword2
tools:
  - my_tool_name
enabled: true
---

## Instructions

Describe when and how the agent should use this skill.
Explain the tools available, expected inputs, and output format.
```

### Frontmatter Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Unique skill identifier (use kebab-case) |
| `description` | string | yes | One-line description |
| `version` | string | no | Semantic version (default: `"0.3.0"`) |
| `triggers` | list[str] | no | Keywords that activate the skill |
| `tools` | list[str] | no | Names of tools defined in `tool.py` |
| `enabled` | bool | no | Whether the skill is active (default: `true`) |

## tool.py Format

Tool implementations subclass `birkin.tools.base.Tool` and must define `spec` (property) and `execute` (async method).

```python
from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolSpec, ToolParameter


class MyTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="my_tool_name",
            description="What this tool does",
            parameters=[
                ToolParameter(
                    name="input_text",
                    type="string",
                    description="The text to process",
                    required=True,
                ),
            ],
            toolset="skills",
        )

    async def execute(self, args: dict, context: ToolContext) -> ToolOutput:
        text = args.get("input_text", "")
        # ... process text ...
        return ToolOutput(success=True, output=f"Result: {text}")
```

### Key Points

- The class name can be anything; Birkin discovers all `Tool` subclasses in the module.
- The `spec.name` must match an entry in the SKILL.md `tools` list.
- `execute()` is async — use `await` for I/O operations.
- Return `ToolOutput(success=False, output="error message")` on failure.

## Testing Locally

1. Place your skill directory under `skills/` in the project root:

   ```
   skills/
     my-skill/
       SKILL.md
       tool.py
   ```

2. Verify discovery:

   ```bash
   birkin skill list
   ```

3. Test the skill in chat:

   ```bash
   birkin chat
   > trigger keyword to activate your skill
   ```

4. Write unit tests using pytest:

   ```python
   from birkin.skills.schema import parse_skill_md
   from birkin.skills.loader import SkillLoader

   def test_my_skill(tmp_path):
       # Copy your skill dir to tmp_path and test
       skill = parse_skill_md(tmp_path / "my-skill")
       assert skill is not None
       assert skill.name == "my-skill"
   ```

## Publishing

1. Push your skill directory to a public git repository:

   ```bash
   git init my-skill
   cd my-skill
   git add SKILL.md tool.py
   git commit -m "Initial skill release"
   git remote add origin https://github.com/you/my-skill.git
   git push -u origin main
   ```

2. Anyone can install it with:

   ```bash
   birkin skill install https://github.com/you/my-skill.git
   ```

3. Remove with:

   ```bash
   birkin skill remove my-skill
   ```

## Best Practices

1. **Use kebab-case** for the skill name and directory (e.g., `code-review`, not `CodeReview`).
2. **Keep SKILL.md instructions clear** — the agent reads them to decide when and how to use your skill.
3. **Version your skill** using semantic versioning (`major.minor.patch`).
4. **Validate inputs** in `tool.py` — never trust external data.
5. **Handle errors gracefully** — return `ToolOutput(success=False, ...)` instead of raising exceptions.
6. **Include triggers** that match natural language phrases users would say.
7. **Keep dependencies minimal** — skills should work with Birkin's existing dependencies.
8. **Add a README** to your git repo explaining what the skill does and how to use it.
