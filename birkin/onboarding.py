"""First-run onboarding wizard (``birkin setup`` / ``birkin onboard``).

A friendly, hermes-style guided setup: provider, model, API key, memory vault,
nightly schedule, and permissions — then prints the execution sequence. Runs
automatically the first time you start birkin with no config.
"""

from __future__ import annotations

import os

from . import config, menu
from .ui import BOLD, CYAN, DIM, GREEN, RESET, YELLOW

_ASCII = r"""
 ██████╗ ██╗██████╗ ██╗  ██╗██╗███╗   ██╗
 ██╔══██╗██║██╔══██╗██║ ██╔╝██║████╗  ██║
 ██████╔╝██║██████╔╝█████╔╝ ██║██╔██╗ ██║
 ██╔══██╗██║██╔══██╗██╔═██╗ ██║██║╚██╗██║
 ██████╔╝██║██║  ██║██║  ██╗██║██║ ╚████║
 ╚═════╝ ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝"""


def _ask(label: str, default: str = "") -> str:
    suffix = f" {DIM}[{default}]{RESET}" if default != "" else ""
    try:
        val = input(f"{label}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return default
    return val or default


def _ask_yesno(label: str, default: bool = False) -> bool:
    return menu.confirm(label, default=default)


def run() -> int:
    cfg = config.load_config()
    first = not config.config_path().exists()

    print(f"{CYAN}{_ASCII}{RESET}")
    print(f" {DIM}The AI agent that actually remembers you.{RESET}\n")
    if first:
        print(f"{BOLD}Welcome — let's set up birkin.{RESET} (Enter accepts the default)\n")
    else:
        print(f"{BOLD}birkin setup{RESET} — Enter keeps the current value.\n")

    # 1. Provider — arrow-select
    providers = ["anthropic", "openai"]
    cur_prov = cfg.get("provider", "anthropic")
    pi = menu.select(f"{BOLD}Provider{RESET} (API backend; local CLI agents are "
                     f"chosen in the next step)", providers,
                     default=providers.index(cur_prov) if cur_prov in providers else 0)
    provider = providers[pi] if pi is not None else cur_prov
    cfg["provider"] = provider

    # 2. Model — arrow-select across API + local CLI agents (claude-code/codex) + Ollama
    from . import models as models_mod
    print(f"\n{BOLD}Model{RESET} — discovering API + local options…")
    found = models_mod.discover(cfg)
    labels = [f"{m.id}  [{m.source}]" + (f" · {m.note}" if m.note else "")
              for m in found]
    cur = cfg.get("model")
    default_i = next((i for i, m in enumerate(found) if m.model_value() == cur), 0)
    mi = menu.select("Choose a model", labels, default=default_i)
    if mi is not None:
        models_mod.apply_selection(cfg, found[mi])
        provider = cfg.get("provider", provider)

    # 3. API key — skipped entirely for local CLI agents (they self-authenticate)
    if cfg.get("provider") in config.CLI_PROVIDERS:
        print(f"\n{GREEN}✓ Using a local CLI agent ({cfg['provider']}); no API key "
              f"needed — it uses its own login.{RESET}")
    else:
        env_name = config.PROVIDER_API_KEY_ENV.get(provider, "ANTHROPIC_API_KEY")
        print(f"\n{BOLD}API key{RESET}")
        if os.environ.get(env_name):
            print(f"  {GREEN}✓ found {env_name} in your environment — using that.{RESET}")
        else:
            print(f"  {DIM}Best practice: export {env_name}. If you enter it here it "
                  f"is stored in plaintext in config.json (chmod 600).{RESET}")
            key = _ask("API key (blank to skip)", "")
            if key:
                cfg["api_key"] = key

    # 4. Memory vault
    print(f"\n{BOLD}Memory{RESET} — birkin keeps an Obsidian vault you can open & edit.")
    vault = _ask("Vault path (blank = ~/.birkin/vault)", cfg.get("vault_path", ""))
    cfg["vault_path"] = vault

    # 5. Nightly self-improvement
    print(f"\n{BOLD}Nightly self-improvement{RESET}")
    hour = _ask("Run hour (0-23)", str(cfg.get("nightly_hour", 4)))
    try:
        cfg["nightly_hour"] = int(hour)
    except ValueError:
        pass
    print(f"  {DIM}Memory & skills update automatically; cron jobs and commands "
          f"are proposed for your approval (`birkin review`).{RESET}")

    # 6. Channels — Telegram (optional)
    channels = dict(cfg.get("channels", {}))
    tg = dict(channels.get("telegram", {}))
    print(f"\n{BOLD}Telegram{RESET} — chat with birkin from your phone (optional).")
    if _ask_yesno("Connect a Telegram bot now?", bool(tg.get("enabled"))):
        print(f"  {DIM}Create a bot with @BotFather → /newbot → copy the token.{RESET}")
        token = _ask("Bot token", tg.get("token", ""))
        if token:
            from .gateway.channels.telegram import verify_token
            print(f"  {DIM}Verifying…{RESET}")
            ok, info = verify_token(token)
            if ok:
                tg = {"enabled": True, "token": token}
                print(f"  {GREEN}✓ connected to @{info}. Message it after "
                      f"`birkin gateway`.{RESET}")
            else:
                tg = {"enabled": False, "token": token}
                print(f"  {YELLOW}⚠ could not verify ({info}). Saved but disabled; "
                      f"fix the token and set channels.telegram.enabled=true.{RESET}")
        else:
            print(f"  {DIM}Skipped — no token entered.{RESET}")
    channels["telegram"] = tg
    cfg["channels"] = channels

    config.save_config(cfg)
    print(f"\n{GREEN}Saved to {config.config_path()}{RESET}")

    # 7. Optional: OS-native daily schedule
    if _ask_yesno("Register a daily OS task so the nightly routine runs even "
                  "without `birkin daemon`?", False):
        from .scheduler import install_os_schedule
        install_os_schedule()

    # 8. Next steps
    print(f"\n{BOLD}You're set. Execution sequence:{RESET}")
    print(f"  {CYAN}birkin{RESET}          start chatting")
    print(f"  {CYAN}birkin gateway{RESET}  run as a service (HTTP / Telegram channels)")
    print(f"  {CYAN}birkin web{RESET}      open the monitoring dashboard")
    print(f"  {CYAN}birkin daemon{RESET}   run the 04:00 self-improvement scheduler")
    print(f"  {CYAN}birkin model{RESET}    change model · {CYAN}birkin tools{RESET}  toggle tools")
    if cfg.get("provider") not in config.CLI_PROVIDERS:
        env_name = config.PROVIDER_API_KEY_ENV.get(cfg.get("provider", "anthropic"),
                                                   "ANTHROPIC_API_KEY")
        if not os.environ.get(env_name) and not cfg.get("api_key"):
            print(f"\n{YELLOW}Note: set {env_name} before chatting.{RESET}")
    return 0
