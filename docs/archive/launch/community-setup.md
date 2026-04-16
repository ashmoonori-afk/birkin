# Community Setup Guide

**Status:** Actionable checklist — complete before launch day.

---

## GitHub Repository Setup

### Discussions

Enable GitHub Discussions with these categories:

| Category | Type | Description |
|----------|------|-------------|
| **Announcements** | Announcement | Release notes, major updates, project news (maintainer-only) |
| **Q&A** | Question/Answer | Setup help, troubleshooting, usage questions |
| **Show & Tell** | Show and tell | Share what you've built with Birkin |
| **Ideas** | Open-ended | Feature ideas, integrations, use cases |
| **General** | Open-ended | Community chat, introductions, off-topic |

### Labels

Add these labels beyond the GitHub defaults:

| Label | Color | Description |
|-------|-------|-------------|
| `good-first-issue` | `#7057ff` | Good for first-time contributors |
| `help-wanted` | `#008672` | Community help appreciated |
| `messaging` | `#0e8a16` | Telegram, Discord, Slack, WhatsApp |
| `skills` | `#1d76db` | Skill system and community skills |
| `security` | `#b60205` | Security-related issues |
| `performance` | `#fbca04` | Performance improvements |
| `documentation` | `#0075ca` | Documentation improvements |
| `ux` | `#d876e3` | User experience and accessibility |

### Issue Templates

Already in place at `.github/ISSUE_TEMPLATE/`:
- `bug_report.yml` — Bug reports
- `feature_request.yml` — Feature requests
- `setup_help.yml` — Setup and installation help
- `skill_submission.yml` — Community skill submissions
- `config.yml` — Template chooser config

---

## Discord Server Structure

### Channels

```
WELCOME
├── #rules                  — Server rules and code of conduct
├── #introductions          — Say hello, share what you're building
└── #getting-started        — Quick start guide, common questions

ANNOUNCEMENTS
├── #announcements          — Release notes, major updates (read-only)
└── #changelog              — Automated release notifications

COMMUNITY
├── #general                — Community chat
├── #support                — Setup help, troubleshooting
├── #showcase               — What people build with Birkin
├── #feature-requests       — Ideas and discussion
└── #korean (한국어 커뮤니티) — Korean-language community

DEVELOPMENT
├── #contributors           — For active code contributors
├── #architecture           — Design discussions, RFC reviews
└── #skills-marketplace     — Skill development and sharing

VOICE
└── #voice-chat             — Drop-in voice for pairing, discussions
```

### Roles

| Role | Color | Permissions |
|------|-------|-------------|
| **Maintainer** | Sage green | All permissions |
| **Contributor** | Terracotta | Access to #contributors, pin messages |
| **Community** | Default | Standard read/write |
| **New Member** | Gray | Read-only in announcements, can post in support |

### Bots

- **GitHub bot** — Post release notifications to #changelog
- **Welcome bot** — Auto-welcome with getting started link
- **Moderation bot** — Basic spam and abuse prevention

### Welcome Message (Pin in #getting-started)

> Welcome to the Birkin community!
>
> **Get started in 5 minutes:**
> 1. `git clone https://github.com/MoonGwanghoon/birkin.git`
> 2. `cd birkin && uv pip install -e ".[all]"`
> 3. `birkin setup`
> 4. `birkin chat`
>
> **Need help?** Post in #support
> **Built something?** Share it in #showcase
> **Have an idea?** Drop it in #feature-requests
>
> **Useful links:**
> - GitHub: https://github.com/MoonGwanghoon/birkin
> - Documentation: [link]
> - Contributing guide: https://github.com/MoonGwanghoon/birkin/blob/main/CONTRIBUTING.md

---

## Community Principles

1. **Respond to issues within 48 hours** — acknowledge, even if no fix yet
2. **Welcome every contributor** — first PR gets a shoutout in #announcements
3. **Transparent roadmap** — public priorities at ROADMAP.md, no hidden agenda
4. **Bilingual support** — English primary, Korean secondary
5. **No gatekeeping** — questions at any skill level are welcome

---

## Pre-Launch Checklist

- [ ] Create Discord server with channel structure above
- [ ] Set up Discord roles and permissions
- [ ] Configure GitHub bot for release notifications
- [ ] Enable GitHub Discussions with categories above
- [ ] Add `good-first-issue` and `help-wanted` labels
- [ ] Pin welcome message in Discord #getting-started
- [ ] Pin CONTRIBUTING.md link in Discord #contributors
- [ ] Create X/Twitter account (@birkin_agent or @birkinai)
- [ ] Set up profile with Birkin Craft brand colors and logo
- [ ] Prepare 3 seed "good first issues" for contributors
- [ ] Record 2-3 minute demo video (setup to chat to Telegram)
- [ ] Verify ROADMAP.md is linked from README

---

*Community building is a daily practice, not a launch-day event.*
