# GitHub Repository Setup Spec

Reference: [BRA-49 Plan Section 4](/BRA/issues/BRA-49#document-plan)

---

## Repository Description

```
AI agent platform that makes powerful AI accessible to everyone. Self-improving agents with messaging-first design.
```

## Repository Topics

Apply these as GitHub repo topics (Settings > Topics):

```
ai-agent
llm
autonomous-agent
chatbot
ai-assistant
self-improving-ai
no-code-ai
cybersecurity
agent-orchestration
mcp
python
telegram-bot
discord-bot
```

## Social Preview Image

**Spec:**
- Dimensions: 1280x640px
- Background: warm neutral (#faf8f5 or brand palette)
- Center: Birkin logo (once finalized)
- Below logo: tagline "AI that works for you, not the other way around."
- Bottom bar: key stats — "200+ Models | Self-Improving | Messaging-First | MIT License"
- Style: clean, modern, approachable — matches brand personality

**Status:** Blocked on logo/visual identity decision.

## Pinned Issues

Create and pin these after repo goes public:

1. **Getting Started Guide** (Discussion, pinned)
   - Links to docs site, quickstart, and messaging setup
   - Welcoming tone for first-time visitors

2. **Roadmap** (Discussion, pinned)
   - Public roadmap with phases
   - Link to GitHub Projects board

3. **Community Showcase** (Discussion, pinned)
   - Thread for users to share what they built with Birkin
   - Categories: automations, skills, integrations

## Issue Labels

Ensure these labels exist with consistent colors:

| Label | Color | Description |
|-------|-------|-------------|
| `good-first-issue` | #7057ff | Good for newcomers |
| `help-wanted` | #008672 | Extra attention is needed |
| `bug` | #d73a4a | Something isn't working |
| `feature-request` | #a2eeef | New feature or request |
| `documentation` | #0075ca | Improvements or additions to documentation |
| `skill-contribution` | #e4e669 | Community skill submission |
| `security` | #ee0701 | Security-related issue |
| `performance` | #fbca04 | Performance improvement |

## GitHub Projects Board

Create a public project board with columns:

- Backlog
- In Progress
- In Review
- Done

## Branch Protection (main)

- Require pull request reviews (1 reviewer)
- Require status checks to pass (CI)
- Require linear history
- No force pushes

## Repository Settings

- Wikis: disabled (use docs site instead)
- Discussions: enabled
- Sponsorships: enabled when ready
- Pages: enabled for landing page (gh-pages branch)
