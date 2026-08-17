# Birkin 설정 참조

Schema version: 1

`config.json`은 희소 override 파일입니다. 생략된 값은 아래 기본값을 사용하며 알 수 없는 확장 키는 보존합니다.

| 경로 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `provider` | `string` | `"codex-cli"` | Birkin 설정 `provider`. |
| `model` | `string` | `"default"` | Birkin 설정 `model`. |
| `subagent_model` | `string` | `"default"` | Birkin 설정 `subagent_model`. |
| `base_url` | `string` | `""` | Birkin 설정 `base_url`. |
| `cli_command` | `array` | `[]` | Birkin 설정 `cli_command`. |
| `api_key` | `any` | `null` | Birkin 설정 `api_key`. |
| `max_tokens` | `integer` | `4096` | Birkin 설정 `max_tokens`. |
| `temperature` | `number` | `1.0` | Birkin 설정 `temperature`. |
| `max_turns` | `integer` | `24` | Birkin 설정 `max_turns`. |
| `auto_compact` | `boolean` | `true` | Birkin 설정 `auto_compact`. |
| `context_window` | `integer` | `200000` | Birkin 설정 `context_window`. |
| `fallback_provider` | `string` | `""` | Birkin 설정 `fallback_provider`. |
| `fallback_model` | `string` | `""` | Birkin 설정 `fallback_model`. |
| `fallback_base_url` | `string` | `""` | Birkin 설정 `fallback_base_url`. |
| `fallback_cooldown` | `integer` | `300` | Birkin 설정 `fallback_cooldown`. |
| `api_keys` | `array` | `[]` | Birkin 설정 `api_keys`. |
| `a2a_enabled` | `boolean` | `false` | Birkin 설정 `a2a_enabled`. |
| `lsp_servers` | `object` | `{}` | Birkin 설정 `lsp_servers`. |
| `spill_threshold` | `integer` | `30000` | Birkin 설정 `spill_threshold`. |
| `spill_dir` | `string` | `""` | Birkin 설정 `spill_dir`. |
| `spill_retention_days` | `integer` | `7` | Birkin 설정 `spill_retention_days`. |
| `redact_secrets` | `boolean` | `true` | Birkin 설정 `redact_secrets`. |
| `repl_typed_line` | `string` | `"steer"` | Birkin 설정 `repl_typed_line`. |
| `moirai_auto` | `boolean` | `false` | Birkin 설정 `moirai_auto`. |
| `moirai_workers` | `integer` | `4` | Birkin 설정 `moirai_workers`. |
| `moirai_max_agents` | `integer` | `100` | Birkin 설정 `moirai_max_agents`. |
| `moirai_roles` | `object` | `{}` | Birkin 설정 `moirai_roles`. |
| `moirai_token_budget` | `integer` | `0` | Birkin 설정 `moirai_token_budget`. |
| `marginalia_api_key` | `string` | `""` | Birkin 설정 `marginalia_api_key`. |
| `parallel_tools` | `boolean` | `true` | Birkin 설정 `parallel_tools`. |
| `parallel_tool_workers` | `integer` | `8` | Birkin 설정 `parallel_tool_workers`. |
| `shell_approval` | `string` | `"manual"` | Birkin 설정 `shell_approval`. |
| `allow_powershell` | `boolean` | `false` | Birkin 설정 `allow_powershell`. |
| `checkpoints` | `boolean` | `true` | Birkin 설정 `checkpoints`. |
| `hooks` | `object` | `{}` | Birkin 설정 `hooks`. |
| `hooks_auto_accept` | `boolean` | `false` | Birkin 설정 `hooks_auto_accept`. |
| `skills_guard_agent_created` | `boolean` | `false` | Birkin 설정 `skills_guard_agent_created`. |
| `checkpoint_keep` | `integer` | `20` | Birkin 설정 `checkpoint_keep`. |
| `command_allowlist` | `array` | `[]` | Birkin 설정 `command_allowlist`. |
| `approval_model` | `string` | `""` | Birkin 설정 `approval_model`. |
| `max_depth` | `integer` | `2` | Birkin 설정 `max_depth`. |
| `extra_skill_dirs` | `array` | `[]` | Birkin 설정 `extra_skill_dirs`. |
| `disabled_tools` | `array` | `[]` | Birkin 설정 `disabled_tools`. |
| `desktop_tools` | `boolean` | `false` | Birkin 설정 `desktop_tools`. |
| `computer_use` | `object` | `{"enabled": false, "allowed_apps": [], "denied_apps": [], "allowed_windows": null, "denied_windows": [], "allowed_operations": ["click", "double_click", "right_click", "middle_click", "drag", "scroll", "type"], "max_actions": 200}` | Birkin 설정 `computer_use`. |
| `computer_use.enabled` | `boolean` | `false` | Birkin 설정 `computer_use.enabled`. |
| `computer_use.allowed_apps` | `array` | `[]` | Birkin 설정 `computer_use.allowed_apps`. |
| `computer_use.denied_apps` | `array` | `[]` | Birkin 설정 `computer_use.denied_apps`. |
| `computer_use.allowed_windows` | `any` | `null` | Birkin 설정 `computer_use.allowed_windows`. |
| `computer_use.denied_windows` | `array` | `[]` | Birkin 설정 `computer_use.denied_windows`. |
| `computer_use.allowed_operations` | `array` | `["click", "double_click", "right_click", "middle_click", "drag", "scroll", "type"]` | Birkin 설정 `computer_use.allowed_operations`. |
| `computer_use.max_actions` | `integer` | `200` | Birkin 설정 `computer_use.max_actions`. |
| `self_improve` | `boolean` | `true` | Birkin 설정 `self_improve`. |
| `skill_nudge_interval` | `integer` | `3` | Birkin 설정 `skill_nudge_interval`. |
| `memory_nudge_interval` | `integer` | `6` | Birkin 설정 `memory_nudge_interval`. |
| `web_port` | `integer` | `8787` | Birkin 설정 `web_port`. |
| `web_remote_access` | `boolean` | `false` | Birkin 설정 `web_remote_access`. |
| `gateway_port` | `integer` | `8788` | Birkin 설정 `gateway_port`. |
| `gateway_model` | `string` | `""` | Birkin 설정 `gateway_model`. |
| `gateway_reasoning_effort` | `string` | `""` | Birkin 설정 `gateway_reasoning_effort`. |
| `gateway_persistent` | `boolean` | `true` | Birkin 설정 `gateway_persistent`. |
| `gateway_allowed_tools` | `array` | `[]` | Birkin 설정 `gateway_allowed_tools`. |
| `repl_warm_session` | `boolean` | `false` | Birkin 설정 `repl_warm_session`. |
| `gateway_clean_hooks` | `boolean` | `true` | Birkin 설정 `gateway_clean_hooks`. |
| `gateway_thinking_tokens` | `integer` | `0` | Birkin 설정 `gateway_thinking_tokens`. |
| `gateway_prewarm` | `boolean` | `true` | Birkin 설정 `gateway_prewarm`. |
| `voice` | `object` | `{"wake_phrase": "Daddy is home", "gateway_url": "", "session_id": "voice-local", "sample_rate": 24000, "stt_model": "gpt-transcribe", "tts_model": "gpt-4o-mini-tts", "tts_voice": "coral", "tts_instructions": "Speak concisely and clearly.", "conversation_style": "", "onboarding_complete": false, "background_workers": 2}` | Birkin 설정 `voice`. |
| `voice.wake_phrase` | `string` | `"Daddy is home"` | Birkin 설정 `voice.wake_phrase`. |
| `voice.gateway_url` | `string` | `""` | Birkin 설정 `voice.gateway_url`. |
| `voice.session_id` | `string` | `"voice-local"` | Birkin 설정 `voice.session_id`. |
| `voice.sample_rate` | `integer` | `24000` | Birkin 설정 `voice.sample_rate`. |
| `voice.stt_model` | `string` | `"gpt-transcribe"` | Birkin 설정 `voice.stt_model`. |
| `voice.tts_model` | `string` | `"gpt-4o-mini-tts"` | Birkin 설정 `voice.tts_model`. |
| `voice.tts_voice` | `string` | `"coral"` | Birkin 설정 `voice.tts_voice`. |
| `voice.tts_instructions` | `string` | `"Speak concisely and clearly."` | Birkin 설정 `voice.tts_instructions`. |
| `voice.conversation_style` | `string` | `""` | Birkin 설정 `voice.conversation_style`. |
| `voice.onboarding_complete` | `boolean` | `false` | Birkin 설정 `voice.onboarding_complete`. |
| `voice.background_workers` | `integer` | `2` | Birkin 설정 `voice.background_workers`. |
| `autosave_transcripts` | `boolean` | `false` | Birkin 설정 `autosave_transcripts`. |
| `autosave_redact_secrets` | `boolean` | `true` | Birkin 설정 `autosave_redact_secrets`. |
| `autosave_max_chars` | `integer` | `4000` | Birkin 설정 `autosave_max_chars`. |
| `autosave_max_turns` | `integer` | `40` | Birkin 설정 `autosave_max_turns`. |
| `autosave_retention_days` | `integer` | `30` | Birkin 설정 `autosave_retention_days`. |
| `autosave_max_files` | `integer` | `500` | Birkin 설정 `autosave_max_files`. |
| `neurosis_threshold` | `any` | `null` | Birkin 설정 `neurosis_threshold`. |
| `neurosis_auto` | `boolean` | `true` | Birkin 설정 `neurosis_auto`. |
| `channels` | `object` | `{"http": {"enabled": true}, "telegram": {"enabled": false, "token": "", "allowed_chat_ids": [], "stream": true}, "slack": {"enabled": false, "webhook_url": "", "allowed_channel_ids": []}, "discord": {"enabled": false, "webhook_url": "", "allowed_channel_ids": []}}` | Birkin 설정 `channels`. |
| `channels.http` | `object` | `{"enabled": true}` | Birkin 설정 `channels.http`. |
| `channels.http.enabled` | `boolean` | `true` | Birkin 설정 `channels.http.enabled`. |
| `channels.telegram` | `object` | `{"enabled": false, "token": "", "allowed_chat_ids": [], "stream": true}` | Birkin 설정 `channels.telegram`. |
| `channels.telegram.enabled` | `boolean` | `false` | Birkin 설정 `channels.telegram.enabled`. |
| `channels.telegram.token` | `string` | `""` | Birkin 설정 `channels.telegram.token`. |
| `channels.telegram.allowed_chat_ids` | `array` | `[]` | Birkin 설정 `channels.telegram.allowed_chat_ids`. |
| `channels.telegram.stream` | `boolean` | `true` | Birkin 설정 `channels.telegram.stream`. |
| `channels.slack` | `object` | `{"enabled": false, "webhook_url": "", "allowed_channel_ids": []}` | Birkin 설정 `channels.slack`. |
| `channels.slack.enabled` | `boolean` | `false` | Birkin 설정 `channels.slack.enabled`. |
| `channels.slack.webhook_url` | `string` | `""` | Birkin 설정 `channels.slack.webhook_url`. |
| `channels.slack.allowed_channel_ids` | `array` | `[]` | Birkin 설정 `channels.slack.allowed_channel_ids`. |
| `channels.discord` | `object` | `{"enabled": false, "webhook_url": "", "allowed_channel_ids": []}` | Birkin 설정 `channels.discord`. |
| `channels.discord.enabled` | `boolean` | `false` | Birkin 설정 `channels.discord.enabled`. |
| `channels.discord.webhook_url` | `string` | `""` | Birkin 설정 `channels.discord.webhook_url`. |
| `channels.discord.allowed_channel_ids` | `array` | `[]` | Birkin 설정 `channels.discord.allowed_channel_ids`. |
| `vault_path` | `string` | `""` | Birkin 설정 `vault_path`. |
| `memory_vector_enabled` | `boolean` | `false` | Birkin 설정 `memory_vector_enabled`. |
| `memory_vector_backend` | `string` | `"sentence-transformers"` | Birkin 설정 `memory_vector_backend`. |
| `memory_vector_model` | `string` | `"all-MiniLM-L6-v2"` | Birkin 설정 `memory_vector_model`. |
| `memory_entity_enabled` | `boolean` | `false` | Birkin 설정 `memory_entity_enabled`. |
| `memory_temporal_enabled` | `boolean` | `false` | Birkin 설정 `memory_temporal_enabled`. |
| `memory_scope` | `string` | `"user"` | 메모리 쓰기에 사용하는 소유 범위입니다. |
| `memory_visible_scopes` | `array` | `["workflow", "agent", "project", "organization", "user"]` | 이 에이전트가 읽을 수 있는 메모리 범위이며 생략된 범위는 닫힌 상태로 거부됩니다. |
| `memory_default_trust` | `string` | `"medium"` | 명시적 매핑이 없는 메모리 출처에 적용하는 신뢰 수준입니다. |
| `memory_source_trust` | `object` | `{}` | 최소 신뢰 쿼리에 사용하는 출처별 메모리 신뢰 수준입니다. |
| `morpheus_deliver_chat_id` | `string` | `""` | Birkin 설정 `morpheus_deliver_chat_id`. |
| `workspace_roots` | `array` | `[]` | Birkin 설정 `workspace_roots`. |
| `reaper_enabled` | `boolean` | `true` | Birkin 설정 `reaper_enabled`. |
| `morpheus_provider` | `string` | `""` | Birkin 설정 `morpheus_provider`. |
| `morpheus_model` | `string` | `""` | Birkin 설정 `morpheus_model`. |
| `morpheus_hour` | `integer` | `7` | Birkin 설정 `morpheus_hour`. |
| `morpheus_minute` | `integer` | `0` | Birkin 설정 `morpheus_minute`. |
| `auto_approve` | `array` | `["memory", "skill"]` | Birkin 설정 `auto_approve`. |
| `harness_enabled` | `boolean` | `true` | Birkin 설정 `harness_enabled`. |
| `harness_turn_interval` | `integer` | `12` | Birkin 설정 `harness_turn_interval`. |
| `harness_cooldown_min` | `integer` | `15` | Birkin 설정 `harness_cooldown_min`. |
| `harness_compact_review` | `boolean` | `true` | Birkin 설정 `harness_compact_review`. |
| `harness_max_edits` | `integer` | `12` | Birkin 설정 `harness_max_edits`. |
| `harness_prompt_budget` | `integer` | `20000` | Birkin 설정 `harness_prompt_budget`. |
| `harness_auto_approve` | `array` | `["memory", "skill_note"]` | Birkin 설정 `harness_auto_approve`. |
| `cli_access` | `string` | `"workspace"` | Birkin 설정 `cli_access`. |
| `cli_network_access` | `boolean` | `false` | Birkin 설정 `cli_network_access`. |
| `egress` | `object` | `{"enabled": true, "enforced": true, "max_bytes": 1048576, "destinations": {}}` | Birkin 설정 `egress`. |
| `egress.enabled` | `boolean` | `true` | Birkin 설정 `egress.enabled`. |
| `egress.enforced` | `boolean` | `true` | Birkin 설정 `egress.enforced`. |
| `egress.max_bytes` | `integer` | `1048576` | Birkin 설정 `egress.max_bytes`. |
| `egress.destinations` | `object` | `{}` | Birkin 설정 `egress.destinations`. |
| `allow_unattended_full` | `boolean` | `false` | Birkin 설정 `allow_unattended_full`. |
| `budget_tokens_daily` | `integer` | `0` | Birkin 설정 `budget_tokens_daily`. |
| `budget_tokens_monthly` | `integer` | `0` | Birkin 설정 `budget_tokens_monthly`. |
| `subagent_tree_max_tokens` | `integer` | `0` | Birkin 설정 `subagent_tree_max_tokens`. |
| `subagent_tree_max_usd` | `number` | `0.0` | Birkin 설정 `subagent_tree_max_usd`. |
| `subagent_tree_deadline_seconds` | `integer` | `0` | Birkin 설정 `subagent_tree_deadline_seconds`. |
| `subagent_tree_max_concurrent` | `integer` | `4` | Birkin 설정 `subagent_tree_max_concurrent`. |
| `subagent_tree_max_nodes` | `integer` | `16` | Birkin 설정 `subagent_tree_max_nodes`. |
| `cli_timeout` | `integer` | `300` | Birkin 설정 `cli_timeout`. |
| `evidence_required` | `boolean` | `false` | Birkin 설정 `evidence_required`. |
| `critique_agents` | `integer` | `3` | Birkin 설정 `critique_agents`. |
| `boulder_max_iters` | `integer` | `100` | Birkin 설정 `boulder_max_iters`. |
| `fs_jail` | `boolean` | `false` | Birkin 설정 `fs_jail`. |
| `sandbox` | `object` | `{"backend": "worktree", "image": "", "setup": [], "env_allowlist": [], "network": "off", "network_allowlist": [], "write_paths": ["."]}` | 격리된 worktree 또는 Docker 작업의 기본값이며 저장소의 .birkin/sandbox.json에서 재정의할 수 있습니다. |
| `sandbox.backend` | `string` | `"worktree"` | Birkin 설정 `sandbox.backend`. |
| `sandbox.image` | `string` | `""` | Birkin 설정 `sandbox.image`. |
| `sandbox.setup` | `array` | `[]` | Birkin 설정 `sandbox.setup`. |
| `sandbox.env_allowlist` | `array` | `[]` | Birkin 설정 `sandbox.env_allowlist`. |
| `sandbox.network` | `string` | `"off"` | Birkin 설정 `sandbox.network`. |
| `sandbox.network_allowlist` | `array` | `[]` | Birkin 설정 `sandbox.network_allowlist`. |
| `sandbox.write_paths` | `array` | `["."]` | Birkin 설정 `sandbox.write_paths`. |
| `update_verify_signature` | `boolean` | `false` | Birkin 설정 `update_verify_signature`. |
| `nightly_hour` | `integer` | `null` |  |
| `nightly_minute` | `integer` | `null` |  |
