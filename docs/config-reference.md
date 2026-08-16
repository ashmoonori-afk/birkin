# Birkin configuration reference

Schema version: 1

`config.json` is a sparse override file. Omitted values use the defaults below, and unknown extension keys are preserved.

| Path | Type | Default | Description |
|---|---|---|---|
| `provider` | `string` | `"codex-cli"` | Birkin setting `provider`. |
| `model` | `string` | `"default"` | Birkin setting `model`. |
| `subagent_model` | `string` | `"default"` | Birkin setting `subagent_model`. |
| `base_url` | `string` | `""` | Birkin setting `base_url`. |
| `cli_command` | `array` | `[]` | Birkin setting `cli_command`. |
| `api_key` | `any` | `null` | Birkin setting `api_key`. |
| `max_tokens` | `integer` | `4096` | Birkin setting `max_tokens`. |
| `temperature` | `number` | `1.0` | Birkin setting `temperature`. |
| `max_turns` | `integer` | `24` | Birkin setting `max_turns`. |
| `auto_compact` | `boolean` | `true` | Birkin setting `auto_compact`. |
| `context_window` | `integer` | `200000` | Birkin setting `context_window`. |
| `fallback_provider` | `string` | `""` | Birkin setting `fallback_provider`. |
| `fallback_model` | `string` | `""` | Birkin setting `fallback_model`. |
| `fallback_base_url` | `string` | `""` | Birkin setting `fallback_base_url`. |
| `fallback_cooldown` | `integer` | `300` | Birkin setting `fallback_cooldown`. |
| `api_keys` | `array` | `[]` | Birkin setting `api_keys`. |
| `a2a_enabled` | `boolean` | `false` | Birkin setting `a2a_enabled`. |
| `lsp_servers` | `object` | `{}` | Birkin setting `lsp_servers`. |
| `spill_threshold` | `integer` | `30000` | Birkin setting `spill_threshold`. |
| `spill_dir` | `string` | `""` | Birkin setting `spill_dir`. |
| `spill_retention_days` | `integer` | `7` | Birkin setting `spill_retention_days`. |
| `redact_secrets` | `boolean` | `true` | Birkin setting `redact_secrets`. |
| `repl_typed_line` | `string` | `"steer"` | Birkin setting `repl_typed_line`. |
| `moirai_auto` | `boolean` | `false` | Birkin setting `moirai_auto`. |
| `moirai_workers` | `integer` | `4` | Birkin setting `moirai_workers`. |
| `moirai_max_agents` | `integer` | `100` | Birkin setting `moirai_max_agents`. |
| `moirai_roles` | `object` | `{}` | Birkin setting `moirai_roles`. |
| `moirai_token_budget` | `integer` | `0` | Birkin setting `moirai_token_budget`. |
| `marginalia_api_key` | `string` | `""` | Birkin setting `marginalia_api_key`. |
| `parallel_tools` | `boolean` | `true` | Birkin setting `parallel_tools`. |
| `parallel_tool_workers` | `integer` | `8` | Birkin setting `parallel_tool_workers`. |
| `shell_approval` | `string` | `"manual"` | Birkin setting `shell_approval`. |
| `allow_powershell` | `boolean` | `false` | Birkin setting `allow_powershell`. |
| `checkpoints` | `boolean` | `true` | Birkin setting `checkpoints`. |
| `hooks` | `object` | `{}` | Birkin setting `hooks`. |
| `hooks_auto_accept` | `boolean` | `false` | Birkin setting `hooks_auto_accept`. |
| `skills_guard_agent_created` | `boolean` | `false` | Birkin setting `skills_guard_agent_created`. |
| `checkpoint_keep` | `integer` | `20` | Birkin setting `checkpoint_keep`. |
| `command_allowlist` | `array` | `[]` | Birkin setting `command_allowlist`. |
| `approval_model` | `string` | `""` | Birkin setting `approval_model`. |
| `max_depth` | `integer` | `2` | Birkin setting `max_depth`. |
| `extra_skill_dirs` | `array` | `[]` | Birkin setting `extra_skill_dirs`. |
| `disabled_tools` | `array` | `[]` | Birkin setting `disabled_tools`. |
| `desktop_tools` | `boolean` | `false` | Birkin setting `desktop_tools`. |
| `computer_use` | `object` | `{"enabled": false, "allowed_apps": [], "denied_apps": [], "allowed_windows": null, "denied_windows": [], "allowed_operations": ["click", "double_click", "right_click", "middle_click", "drag", "scroll", "type"], "max_actions": 200}` | Birkin setting `computer_use`. |
| `computer_use.enabled` | `boolean` | `false` | Birkin setting `computer_use.enabled`. |
| `computer_use.allowed_apps` | `array` | `[]` | Birkin setting `computer_use.allowed_apps`. |
| `computer_use.denied_apps` | `array` | `[]` | Birkin setting `computer_use.denied_apps`. |
| `computer_use.allowed_windows` | `any` | `null` | Birkin setting `computer_use.allowed_windows`. |
| `computer_use.denied_windows` | `array` | `[]` | Birkin setting `computer_use.denied_windows`. |
| `computer_use.allowed_operations` | `array` | `["click", "double_click", "right_click", "middle_click", "drag", "scroll", "type"]` | Birkin setting `computer_use.allowed_operations`. |
| `computer_use.max_actions` | `integer` | `200` | Birkin setting `computer_use.max_actions`. |
| `self_improve` | `boolean` | `true` | Birkin setting `self_improve`. |
| `skill_nudge_interval` | `integer` | `3` | Birkin setting `skill_nudge_interval`. |
| `memory_nudge_interval` | `integer` | `6` | Birkin setting `memory_nudge_interval`. |
| `web_port` | `integer` | `8787` | Birkin setting `web_port`. |
| `web_remote_access` | `boolean` | `false` | Birkin setting `web_remote_access`. |
| `gateway_port` | `integer` | `8788` | Birkin setting `gateway_port`. |
| `gateway_model` | `string` | `""` | Birkin setting `gateway_model`. |
| `gateway_reasoning_effort` | `string` | `""` | Birkin setting `gateway_reasoning_effort`. |
| `gateway_persistent` | `boolean` | `true` | Birkin setting `gateway_persistent`. |
| `gateway_allowed_tools` | `array` | `[]` | Birkin setting `gateway_allowed_tools`. |
| `repl_warm_session` | `boolean` | `false` | Birkin setting `repl_warm_session`. |
| `gateway_clean_hooks` | `boolean` | `true` | Birkin setting `gateway_clean_hooks`. |
| `gateway_thinking_tokens` | `integer` | `0` | Birkin setting `gateway_thinking_tokens`. |
| `gateway_prewarm` | `boolean` | `true` | Birkin setting `gateway_prewarm`. |
| `office` | `object` | `{"handoc": {"node_path": "", "node_version": "22.14.0", "module_root": "", "package_manifest_sha256": "", "timeout_seconds": 30}}` | Birkin setting `office`. |
| `office.handoc` | `object` | `{"node_path": "", "node_version": "22.14.0", "module_root": "", "package_manifest_sha256": "", "timeout_seconds": 30}` | Birkin setting `office.handoc`. |
| `office.handoc.node_path` | `string` | `""` | Birkin setting `office.handoc.node_path`. |
| `office.handoc.node_version` | `string` | `"22.14.0"` | Birkin setting `office.handoc.node_version`. |
| `office.handoc.module_root` | `string` | `""` | Birkin setting `office.handoc.module_root`. |
| `office.handoc.package_manifest_sha256` | `string` | `""` | Birkin setting `office.handoc.package_manifest_sha256`. |
| `office.handoc.timeout_seconds` | `integer` | `30` | Birkin setting `office.handoc.timeout_seconds`. |
| `voice` | `object` | `{"wake_phrase": "Daddy is home", "gateway_url": "", "session_id": "voice-local", "sample_rate": 24000, "stt_model": "gpt-transcribe", "tts_model": "gpt-4o-mini-tts", "tts_voice": "coral", "tts_instructions": "Speak concisely and clearly.", "conversation_style": "", "onboarding_complete": false, "background_workers": 2}` | Birkin setting `voice`. |
| `voice.wake_phrase` | `string` | `"Daddy is home"` | Birkin setting `voice.wake_phrase`. |
| `voice.gateway_url` | `string` | `""` | Birkin setting `voice.gateway_url`. |
| `voice.session_id` | `string` | `"voice-local"` | Birkin setting `voice.session_id`. |
| `voice.sample_rate` | `integer` | `24000` | Birkin setting `voice.sample_rate`. |
| `voice.stt_model` | `string` | `"gpt-transcribe"` | Birkin setting `voice.stt_model`. |
| `voice.tts_model` | `string` | `"gpt-4o-mini-tts"` | Birkin setting `voice.tts_model`. |
| `voice.tts_voice` | `string` | `"coral"` | Birkin setting `voice.tts_voice`. |
| `voice.tts_instructions` | `string` | `"Speak concisely and clearly."` | Birkin setting `voice.tts_instructions`. |
| `voice.conversation_style` | `string` | `""` | Birkin setting `voice.conversation_style`. |
| `voice.onboarding_complete` | `boolean` | `false` | Birkin setting `voice.onboarding_complete`. |
| `voice.background_workers` | `integer` | `2` | Birkin setting `voice.background_workers`. |
| `autosave_transcripts` | `boolean` | `false` | Birkin setting `autosave_transcripts`. |
| `autosave_redact_secrets` | `boolean` | `true` | Birkin setting `autosave_redact_secrets`. |
| `autosave_max_chars` | `integer` | `4000` | Birkin setting `autosave_max_chars`. |
| `autosave_max_turns` | `integer` | `40` | Birkin setting `autosave_max_turns`. |
| `autosave_retention_days` | `integer` | `30` | Birkin setting `autosave_retention_days`. |
| `autosave_max_files` | `integer` | `500` | Birkin setting `autosave_max_files`. |
| `neurosis_threshold` | `any` | `null` | Birkin setting `neurosis_threshold`. |
| `neurosis_auto` | `boolean` | `true` | Birkin setting `neurosis_auto`. |
| `channels` | `object` | `{"http": {"enabled": true}, "telegram": {"enabled": false, "token": "", "allowed_chat_ids": [], "stream": true}, "slack": {"enabled": false, "webhook_url": ""}, "discord": {"enabled": false, "webhook_url": ""}}` | Birkin setting `channels`. |
| `channels.http` | `object` | `{"enabled": true}` | Birkin setting `channels.http`. |
| `channels.http.enabled` | `boolean` | `true` | Birkin setting `channels.http.enabled`. |
| `channels.telegram` | `object` | `{"enabled": false, "token": "", "allowed_chat_ids": [], "stream": true}` | Birkin setting `channels.telegram`. |
| `channels.telegram.enabled` | `boolean` | `false` | Birkin setting `channels.telegram.enabled`. |
| `channels.telegram.token` | `string` | `""` | Birkin setting `channels.telegram.token`. |
| `channels.telegram.allowed_chat_ids` | `array` | `[]` | Birkin setting `channels.telegram.allowed_chat_ids`. |
| `channels.telegram.stream` | `boolean` | `true` | Birkin setting `channels.telegram.stream`. |
| `channels.slack` | `object` | `{"enabled": false, "webhook_url": ""}` | Birkin setting `channels.slack`. |
| `channels.slack.enabled` | `boolean` | `false` | Birkin setting `channels.slack.enabled`. |
| `channels.slack.webhook_url` | `string` | `""` | Birkin setting `channels.slack.webhook_url`. |
| `channels.discord` | `object` | `{"enabled": false, "webhook_url": ""}` | Birkin setting `channels.discord`. |
| `channels.discord.enabled` | `boolean` | `false` | Birkin setting `channels.discord.enabled`. |
| `channels.discord.webhook_url` | `string` | `""` | Birkin setting `channels.discord.webhook_url`. |
| `vault_path` | `string` | `""` | Birkin setting `vault_path`. |
| `memory_vector_enabled` | `boolean` | `false` | Birkin setting `memory_vector_enabled`. |
| `memory_vector_backend` | `string` | `"sentence-transformers"` | Birkin setting `memory_vector_backend`. |
| `memory_vector_model` | `string` | `"all-MiniLM-L6-v2"` | Birkin setting `memory_vector_model`. |
| `memory_entity_enabled` | `boolean` | `false` | Birkin setting `memory_entity_enabled`. |
| `memory_temporal_enabled` | `boolean` | `false` | Birkin setting `memory_temporal_enabled`. |
| `memory_scope` | `string` | `"user"` | Owning scope used for memory writes. |
| `memory_visible_scopes` | `array` | `["workflow", "agent", "project", "organization", "user"]` | Memory scopes this agent may read; omitted scopes fail closed. |
| `memory_default_trust` | `string` | `"medium"` | Trust assigned to memory sources without an explicit mapping. |
| `memory_source_trust` | `object` | `{}` | Per-source memory trust levels used by minimum-trust queries. |
| `morpheus_deliver_chat_id` | `string` | `""` | Birkin setting `morpheus_deliver_chat_id`. |
| `workspace_roots` | `array` | `[]` | Birkin setting `workspace_roots`. |
| `reaper_enabled` | `boolean` | `true` | Birkin setting `reaper_enabled`. |
| `morpheus_provider` | `string` | `""` | Birkin setting `morpheus_provider`. |
| `morpheus_model` | `string` | `""` | Birkin setting `morpheus_model`. |
| `morpheus_hour` | `integer` | `7` | Birkin setting `morpheus_hour`. |
| `morpheus_minute` | `integer` | `0` | Birkin setting `morpheus_minute`. |
| `auto_approve` | `array` | `["memory", "skill"]` | Birkin setting `auto_approve`. |
| `harness_enabled` | `boolean` | `true` | Birkin setting `harness_enabled`. |
| `harness_turn_interval` | `integer` | `12` | Birkin setting `harness_turn_interval`. |
| `harness_cooldown_min` | `integer` | `15` | Birkin setting `harness_cooldown_min`. |
| `harness_compact_review` | `boolean` | `true` | Birkin setting `harness_compact_review`. |
| `harness_max_edits` | `integer` | `12` | Birkin setting `harness_max_edits`. |
| `harness_prompt_budget` | `integer` | `20000` | Birkin setting `harness_prompt_budget`. |
| `harness_auto_approve` | `array` | `["memory", "skill_note"]` | Birkin setting `harness_auto_approve`. |
| `cli_access` | `string` | `"workspace"` | Birkin setting `cli_access`. |
| `cli_network_access` | `boolean` | `false` | Birkin setting `cli_network_access`. |
| `egress` | `object` | `{"enabled": true, "enforced": true, "max_bytes": 1048576, "destinations": {}}` | Birkin setting `egress`. |
| `egress.enabled` | `boolean` | `true` | Birkin setting `egress.enabled`. |
| `egress.enforced` | `boolean` | `true` | Birkin setting `egress.enforced`. |
| `egress.max_bytes` | `integer` | `1048576` | Birkin setting `egress.max_bytes`. |
| `egress.destinations` | `object` | `{}` | Birkin setting `egress.destinations`. |
| `allow_unattended_full` | `boolean` | `false` | Birkin setting `allow_unattended_full`. |
| `budget_tokens_daily` | `integer` | `0` | Birkin setting `budget_tokens_daily`. |
| `budget_tokens_monthly` | `integer` | `0` | Birkin setting `budget_tokens_monthly`. |
| `subagent_tree_max_tokens` | `integer` | `0` | Birkin setting `subagent_tree_max_tokens`. |
| `subagent_tree_max_usd` | `number` | `0.0` | Birkin setting `subagent_tree_max_usd`. |
| `subagent_tree_deadline_seconds` | `integer` | `0` | Birkin setting `subagent_tree_deadline_seconds`. |
| `subagent_tree_max_concurrent` | `integer` | `4` | Birkin setting `subagent_tree_max_concurrent`. |
| `subagent_tree_max_nodes` | `integer` | `16` | Birkin setting `subagent_tree_max_nodes`. |
| `cli_timeout` | `integer` | `300` | Birkin setting `cli_timeout`. |
| `evidence_required` | `boolean` | `false` | Birkin setting `evidence_required`. |
| `critique_agents` | `integer` | `3` | Birkin setting `critique_agents`. |
| `boulder_max_iters` | `integer` | `100` | Birkin setting `boulder_max_iters`. |
| `fs_jail` | `boolean` | `false` | Birkin setting `fs_jail`. |
| `sandbox` | `object` | `{"backend": "worktree", "image": "", "setup": [], "env_allowlist": [], "network": "off", "network_allowlist": [], "write_paths": ["."]}` | Defaults for isolated worktree or Docker jobs; repositories may override them in .birkin/sandbox.json. |
| `sandbox.backend` | `string` | `"worktree"` | Birkin setting `sandbox.backend`. |
| `sandbox.image` | `string` | `""` | Birkin setting `sandbox.image`. |
| `sandbox.setup` | `array` | `[]` | Birkin setting `sandbox.setup`. |
| `sandbox.env_allowlist` | `array` | `[]` | Birkin setting `sandbox.env_allowlist`. |
| `sandbox.network` | `string` | `"off"` | Birkin setting `sandbox.network`. |
| `sandbox.network_allowlist` | `array` | `[]` | Birkin setting `sandbox.network_allowlist`. |
| `sandbox.write_paths` | `array` | `["."]` | Birkin setting `sandbox.write_paths`. |
| `update_verify_signature` | `boolean` | `false` | Birkin setting `update_verify_signature`. |
| `nightly_hour` | `integer` | `null` |  |
| `nightly_minute` | `integer` | `null` |  |
