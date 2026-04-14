# Migrating from OpenClaw to Birkin

This guide covers how to import your OpenClaw settings, memories, skills, and API keys into Birkin.

## Three Ways to Migrate

### 1. Automatic (during first-time setup)

When you run `birkin setup` for the first time and Birkin detects `~/.openclaw`, it automatically offers to import your OpenClaw data before configuration begins. Just accept the prompt and everything is handled for you.

### 2. CLI Command (quick, scriptable)

```bash
birkin claw migrate                      # Preview then migrate (always shows preview first)
birkin claw migrate --dry-run            # Preview only, no changes
birkin claw migrate --preset user-data   # Migrate without API keys/secrets
birkin claw migrate --yes                # Skip confirmation prompt
```

The migration always shows a full preview of what will be imported before making any changes. You review the preview and confirm before anything is written.

**All options:**

| Flag | Description |
|------|-------------|
| `--source PATH` | Path to OpenClaw directory (default: `~/.openclaw`) |
| `--dry-run` | Preview only — no files are modified |
| `--preset {user-data,full}` | Migration preset (default: `full`). `user-data` excludes secrets |
| `--overwrite` | Overwrite existing files (default: skip conflicts) |
| `--migrate-secrets` | Include allowlisted secrets (auto-enabled with `full` preset) |
| `--workspace-target PATH` | Copy workspace instructions (AGENTS.md) to this absolute path |
| `--skill-conflict {skip,overwrite,rename}` | How to handle skill name conflicts (default: `skip`) |
| `--yes`, `-y` | Skip confirmation prompts |

### 3. Agent-Guided (interactive, with previews)

Ask the agent to run the migration for you:

```
> Migrate my OpenClaw setup to Birkin
```

The agent will use the `openclaw-migration` skill to:
1. Run a preview first to show what would change
2. Ask about conflict resolution (SOUL.md, skills, etc.)
3. Let you choose between `user-data` and `full` presets
4. Execute the migration with your choices
5. Print a detailed summary of what was migrated

## What Gets Migrated

### `user-data` preset
| Item | Source | Destination |
|------|--------|-------------|
| SOUL.md | `~/.openclaw/workspace/SOUL.md` | `~/.birkin/SOUL.md` |
| Memory entries | `~/.openclaw/workspace/MEMORY.md` | `~/.birkin/memories/MEMORY.md` |
| User profile | `~/.openclaw/workspace/USER.md` | `~/.birkin/memories/USER.md` |
| Skills | `~/.openclaw/workspace/skills/` | `~/.birkin/skills/openclaw-imports/` |
| Command allowlist | `~/.openclaw/workspace/exec_approval_patterns.yaml` | Merged into `~/.birkin/config.yaml` |
| Messaging settings | `~/.openclaw/config.yaml` (TELEGRAM_ALLOWED_USERS, MESSAGING_CWD) | `~/.birkin/.env` |
| TTS assets | `~/.openclaw/workspace/tts/` | `~/.birkin/tts/` |

Workspace files are also checked at `workspace.default/` and `workspace-main/` as fallback paths (OpenClaw renamed `workspace/` to `workspace-main/` in recent versions).

### `full` preset (adds to `user-data`)
| Item | Source | Destination |
|------|--------|-------------|
| Telegram bot token | `openclaw.json` channels config | `~/.birkin/.env` |
| OpenRouter API key | `.env`, `openclaw.json`, or `openclaw.json["env"]` | `~/.birkin/.env` |
| OpenAI API key | `.env`, `openclaw.json`, or `openclaw.json["env"]` | `~/.birkin/.env` |
| Anthropic API key | `.env`, `openclaw.json`, or `openclaw.json["env"]` | `~/.birkin/.env` |
| ElevenLabs API key | `.env`, `openclaw.json`, or `openclaw.json["env"]` | `~/.birkin/.env` |

API keys are searched across four sources: inline config values, `~/.openclaw/.env`, the `openclaw.json` `"env"` sub-object, and per-agent auth profiles.

Only allowlisted secrets are ever imported. Other credentials are skipped and reported.

## OpenClaw Schema Compatibility

The migration handles both old and current OpenClaw config layouts:

- **Channel tokens**: Reads from flat paths (`channels.telegram.botToken`) and the newer `accounts.default` layout (`channels.telegram.accounts.default.botToken`)
- **TTS provider**: OpenClaw renamed "edge" to "microsoft" — both are recognized and mapped to Birkin' "edge"
- **Provider API types**: Both short (`openai`, `anthropic`) and hyphenated (`openai-completions`, `anthropic-messages`, `google-generative-ai`) values are mapped correctly
- **thinkingDefault**: All enum values are handled including newer ones (`minimal`, `xhigh`, `adaptive`)
- **Matrix**: Uses `accessToken` field (not `botToken`)
- **SecretRef formats**: Plain strings, env templates (`${VAR}`), and `source: "env"` SecretRefs are resolved. `source: "file"` and `source: "exec"` SecretRefs produce a warning — add those keys manually after migration.

## Conflict Handling

By default, the migration **will not overwrite** existing Birkin data:

- **SOUL.md** — skipped if one already exists in `~/.birkin/`
- **Memory entries** — skipped if memories already exist (to avoid duplicates)
- **Skills** — skipped if a skill with the same name already exists
- **API keys** — skipped if the key is already set in `~/.birkin/.env`

To overwrite conflicts, use `--overwrite`. The migration creates backups before overwriting.

For skills, you can also use `--skill-conflict rename` to import conflicting skills under a new name (e.g., `skill-name-imported`).

## Migration Report

Every migration produces a report showing:
- **Migrated items** — what was successfully imported
- **Conflicts** — items skipped because they already exist
- **Skipped items** — items not found in the source
- **Errors** — items that failed to import

For executed migrations, the full report is saved to `~/.birkin/migration/openclaw/<timestamp>/`.

## Post-Migration Notes

- **Skills require a new session** — imported skills take effect after restarting your agent or starting a new chat.
- **WhatsApp requires re-pairing** — WhatsApp uses QR-code pairing, not token-based auth. Run `birkin whatsapp` to pair.
- **Archive cleanup** — after migration, you'll be offered to rename `~/.openclaw/` to `.openclaw.pre-migration/` to prevent state confusion. You can also run `birkin claw cleanup` later.

## Troubleshooting

### "OpenClaw directory not found"
The migration looks for `~/.openclaw` by default, then tries `~/.clawdbot` and `~/.moltbot`. If your OpenClaw is installed elsewhere, use `--source`:
```bash
birkin claw migrate --source /path/to/.openclaw
```

### "Migration script not found"
The migration script ships with Birkin. If you installed via pip (not git clone), the `optional-skills/` directory may not be present. Install the skill from the Skills Hub:
```bash
birkin skills install openclaw-migration
```

### Memory overflow
If your OpenClaw MEMORY.md or USER.md exceeds Birkin' character limits, excess entries are exported to an overflow file in the migration report directory. You can manually review and add the most important ones.

### API keys not found
Keys might be stored in different places depending on your OpenClaw setup:
- `~/.openclaw/.env` file
- Inline in `openclaw.json` under `models.providers.*.apiKey`
- In `openclaw.json` under the `"env"` or `"env.vars"` sub-objects
- In `~/.openclaw/agents/main/agent/auth-profiles.json`

The migration checks all four. If keys use `source: "file"` or `source: "exec"` SecretRefs, they can't be resolved automatically — add them via `birkin config set`.
