"""First-run onboarding wizard (``birkin setup`` / ``birkin onboard``).

A friendly, hermes-style guided setup: provider, model, API key, memory vault,
Morpheus schedule (the nightly self-improvement routine), and permissions —
then prints the execution sequence. Runs automatically the first time you
start birkin with no config.
"""

from __future__ import annotations

import os
import sys

from . import config, menu, persona, provider_onboarding
from .ui import BIRKIN_BANNER, BOLD, CYAN, DIM, GREEN, RESET, YELLOW


def _ask(label: str, default: str = "") -> str:
    suffix = f" {DIM}[{default}]{RESET}" if default != "" else ""
    try:
        val = input(f"{label}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return default
    return val or default


def _ask_yesno(label: str, default: bool = False) -> bool:
    return menu.confirm(label, default=default)


def _api_key_environment_command(
    env_name: str,
    platform_name: str | None = None,
) -> str:
    platform = platform_name or sys.platform
    if platform == "win32":
        return f'$env:{env_name} = "<API key>"'
    return f'export {env_name}="<API key>"'


def _choose_provider(current: str) -> str | None:
    providers = ["codex-cli", "claude-cli", "anthropic", "openai"]
    while True:
        selected = menu.select(
            f"{BOLD}프로바이더{RESET}",
            providers,
            default=(
                providers.index(current)
                if current in providers
                else 0
            ),
        )
        if selected is None:
            return None
        provider = providers[selected]
        if provider != "codex-cli":
            return provider
        while True:
            status = provider_onboarding.probe_codex()
            if status.usable:
                print(
                    f"  {GREEN}✓ Codex CLI 확인: "
                    + f"{status.path}{RESET}",
                )
                return provider
            print(
                f"\n{YELLOW}"
                + f"{provider_onboarding.codex_recovery_text(status)}"
                + f"{RESET}",
            )
            recovery = menu.select(
                f"{BOLD}Codex CLI 복구{RESET}",
                list(provider_onboarding.CODEX_RECOVERY_OPTIONS),
                default=0,
            )
            if recovery is None:
                return None
            match provider_onboarding.recovery_action(recovery):
                case provider_onboarding.CodexRecoveryAction.RETRY:
                    continue
                case provider_onboarding.CodexRecoveryAction.CHOOSE_PROVIDER:
                    break


def run() -> int:
    cfg = config.load_config()
    first = not config.config_path().exists()

    print(f"{CYAN}{BIRKIN_BANNER}{RESET}")
    print(f" {DIM}당신을 실제로 기억하는 AI 에이전트입니다.{RESET}\n")
    if first:
        print(
            f"{BOLD}환영합니다 — Birkin을 설정합니다.{RESET} "
            + "(Enter를 누르면 기본값을 사용합니다)\n",
        )
    else:
        print(
            f"{BOLD}birkin setup{RESET} — Enter를 누르면 현재 값을 유지합니다.\n",
        )

    # 1. Provider — arrow-select
    print(
        f"{DIM}팁: 기본값인 Codex CLI는 기존 OAuth 로그인을 사용합니다. "
        + f"Claude CLI와 유료 API 프로바이더도 선택할 수 있습니다.{RESET}",
    )
    provider = _choose_provider(str(cfg.get("provider", "codex-cli")))
    if provider is None:
        print(f"\n{YELLOW}설정을 저장하지 않고 종료했습니다.{RESET}")
        return 1
    cfg["provider"] = provider

    # 2. Model — arrow-select across API + local CLI agents (claude-code/codex) + Ollama
    from . import models as models_mod
    print(f"\n{BOLD}모델{RESET} — API와 로컬 옵션을 찾는 중…")
    if models_mod.pick_interactive(cfg) is not None:
        provider = cfg.get("provider", provider)

    # 3. API key — skipped entirely for local CLI agents (they self-authenticate)
    if cfg.get("provider") in config.CLI_PROVIDERS:
        print(
            f"\n{GREEN}✓ 로컬 CLI 에이전트({cfg['provider']})를 사용합니다. "
            + f"자체 로그인을 사용하므로 API key가 필요하지 않습니다.{RESET}",
        )
    else:
        env_name = config.PROVIDER_API_KEY_ENV.get(provider, "ANTHROPIC_API_KEY")
        print(f"\n{BOLD}API key{RESET}")
        if os.environ.get(env_name):
            print(
                f"  {GREEN}✓ 환경에서 {env_name}을(를) 찾아 사용합니다.{RESET}",
            )
        else:
            command = _api_key_environment_command(env_name)
            print(
                f"  {DIM}권장: `{command}`로 현재 shell에 설정하세요. "
                + "여기에 입력하면 config.json에 plaintext로 저장됩니다 "
                + f"(소유자 전용 권한).{RESET}",
            )
            key = _ask("API key (비워두면 건너뜀)", "")
            if key:
                cfg["api_key"] = key

    # 4. Memory vault
    print(
        f"\n{BOLD}메모리{RESET} — 열고 편집할 수 있는 Obsidian vault에 저장합니다.",
    )
    vault = _ask(
        "Vault 경로 (비워두면 ~/.birkin/vault)",
        cfg.get("vault_path", ""),
    )
    cfg["vault_path"] = vault
    if sys.platform == "win32":
        print(
            f"  {DIM}비밀이 아닌 Birkin data 경로를 영구 설정하려면: "
            + 'setx BIRKIN_HOME "$env:USERPROFILE\\.birkin"'
            + f"{RESET}",
        )

    # 5. Morpheus (nightly self-improvement)
    print(f"\n{BOLD}Morpheus — 매일 실행되는 자기 개선{RESET}")
    hour = _ask(
        "실행 시각 (0-23)",
        str(cfg.get("morpheus_hour", cfg.get("nightly_hour", 7))),
    )
    try:
        cfg["morpheus_hour"] = int(hour)
    except ValueError:
        pass
    print(
        f"  {DIM}메모리와 skill은 자동으로 갱신되며 cron job과 command는 "
        + f"승인을 요청합니다 (`birkin review`).{RESET}",
    )

    # 6. Channels — Telegram (optional)
    channels = dict(cfg.get("channels", {}))
    tg = dict(channels.get("telegram", {}))
    print(f"\n{BOLD}Telegram{RESET} — 휴대폰에서 대화합니다 (선택 사항).")
    if _ask_yesno("지금 Telegram bot을 연결할까요?", bool(tg.get("enabled"))):
        print(
            f"  {DIM}@BotFather → /newbot으로 bot을 만들고 token을 복사하세요."
            + f"{RESET}",
        )
        token = _ask("Bot token", tg.get("token", ""))
        if token:
            from .gateway.channels.telegram import verify_token
            print(f"  {DIM}확인 중…{RESET}")
            ok, info = verify_token(token)
            if ok:
                tg = {"enabled": True, "token": token}
                print(
                    f"  {GREEN}✓ @{info}에 연결했습니다. `birkin gateway` 실행 후 "
                    + f"메시지를 보내세요.{RESET}",
                )
            else:
                tg = {"enabled": False, "token": token}
                print(
                    f"  {YELLOW}⚠ 확인할 수 없습니다 ({info}). 비활성 상태로 "
                    + "저장했습니다. token을 수정하고 "
                    + f"channels.telegram.enabled=true로 설정하세요.{RESET}",
                )
        else:
            print(f"  {DIM}건너뜀 — token을 입력하지 않았습니다.{RESET}")
    channels["telegram"] = tg
    cfg["channels"] = channels

    config.save_config(cfg)
    print(f"\n{GREEN}{config.config_path()}에 저장했습니다.{RESET}")

    # Persona — seed an editable SOUL.md so the user can shape birkin's voice.
    if persona.seed_default():
        print(
            f"  {DIM}Persona를 {persona.soul_path()}에 만들었습니다. 직접 편집하거나 "
            + f"/personality warm|concise|mentor|direct를 사용하세요.{RESET}",
        )

    # 7. Optional: OS-native daily schedule
    if _ask_yesno(
        "`birkin daemon` 없이도 Morpheus가 실행되도록 매일 OS task를 등록할까요?",
        False,
    ):
        from .scheduler import install_os_schedule
        install_os_schedule()

    # 8. Next steps
    print(f"\n{BOLD}설정이 끝났습니다. 실행 순서:{RESET}")
    print(f"  {CYAN}birkin{RESET}          대화 시작")
    print(f"  {CYAN}birkin gateway{RESET}  서비스 실행 (HTTP / Telegram channel)")
    print(f"  {CYAN}birkin web{RESET}      모니터링 dashboard 열기")
    print(f"  {CYAN}birkin daemon{RESET}   07:00 자기 개선 scheduler 실행")
    print(
        f"  {CYAN}birkin model{RESET}    모델 변경 · "
        + f"{CYAN}birkin tools{RESET}  tool 켜기/끄기",
    )
    if cfg.get("provider") not in config.CLI_PROVIDERS:
        env_name = config.PROVIDER_API_KEY_ENV.get(cfg.get("provider", "anthropic"),
                                                   "ANTHROPIC_API_KEY")
        if not os.environ.get(env_name) and not cfg.get("api_key"):
            command = _api_key_environment_command(env_name)
            print(
                f"\n{YELLOW}대화 전에 `{command}`로 API key를 설정하세요.{RESET}",
            )
    return 0
