"""Choosing who runs each role, before the run starts.

The signals here are deliberately *not* dollars. birkin's usual path is
claude-cli or codex-cli, where a per-token price does not exist — the user is
on a subscription or a CLI login — so a price tag would be a category error on
most runs, and a list price goes stale besides. What a person actually regrets
at a launcher is waiting forty minutes, or being cut off half-way by the budget
gate. So the launcher shows:

- **weight** — the model family's relative heft, from ``presets.family_of``.
  A relative grade never goes stale and reads the same on a CLI or an API.
- **expected duration** — the median of what *this machine* actually measured
  for that (provider, model), from the journal; a published figure only until
  the first real run replaces it.
- **budget footprint** — expected tokens against the remaining daily budget,
  so a run that would trip the gate says so before it starts, not at agent
  eight. Hidden entirely when no cap is set.

Every estimate is marked ``~``, and anything with no basis prints ``—`` rather
than a confident invention.
"""

from __future__ import annotations

from typing import Any, Optional

from .. import budget as _budget
from .. import menu, models, presets, ui
from . import bindings as B
from . import journal
from .bindings import Binding

# Relative heft by model family. Not a price: an ordering that stays true when
# vendors reprice, and that means something for CLI logins too.
WEIGHT_BY_FAMILY = {
    "opus": 3, "gpt": 3, "fable": 3,
    "sonnet": 2,
    "haiku": 1, "spark": 1, "local": 1,
}
WEIGHT_GLYPHS = {1: "●○○", 2: "●●○", 3: "●●●"}
WEIGHT_WORDS = {1: "경량", 2: "표준", 3: "중량"}

# Published measurements, used only until this machine has its own. Sources:
# ADR-046 (codex warm 2.7-3.2s, one-shot 37.5s) and ADR-045 (claude warm ~3s,
# `claude -p` ~8s). Moirai spawns one-shot today, so the one-shot figures apply.
SEEDED_SECONDS = {"codex": 20.0, "claude": 12.0, "anthropic": 8.0,
                  "openai": 8.0, "gemini": 8.0, "local": 5.0}
SEEDED_TOKENS = 400


def weight_of(model: str) -> int:
    return WEIGHT_BY_FAMILY.get(presets.family_of(model or ""), 2)


def weight_glyph(model: str) -> str:
    return WEIGHT_GLYPHS[weight_of(model)]


def estimate(binding: Binding, calls: int) -> dict[str, Any]:
    """Per-role expectation: seconds, tokens, and whether it is measured."""
    seen = journal.observed(binding.provider, binding.model)
    if seen:
        secs, toks, measured = seen["seconds"], seen["tokens"], True
    else:
        secs = SEEDED_SECONDS.get(binding.provider, 10.0)
        toks, measured = float(SEEDED_TOKENS), False
    return {"seconds": secs, "tokens": toks, "measured": measured,
            "calls": max(0, int(calls)),
            "total_seconds": secs * max(0, int(calls)),
            "total_tokens": toks * max(0, int(calls))}


def budget_footprint(total_tokens: float, cfg: dict) -> Optional[float]:
    """Fraction of today's remaining token budget this run would use.

    None when no cap is configured — the column then hides itself rather than
    showing a meaningless 0 %.
    """
    try:
        status = _budget.status(cfg)
    except Exception:
        return None
    cap = int(status.get("daily_cap") or 0)
    if cap <= 0:
        return None
    remaining = max(0, cap - int(status.get("used_today") or 0))
    if remaining <= 0:
        return 1.0
    return total_tokens / remaining


def plan_table(bindings: dict[str, Binding], counts: dict[str, int],
               cfg: dict) -> str:
    """The confirmation block: what will run, how heavy, how long, how much."""
    rows: list[tuple[str, ...]] = []
    total_seconds = 0.0
    total_tokens = 0.0
    any_estimate = False
    any_guess = False

    for role, b in bindings.items():
        n = counts.get(role, 0)
        est = estimate(b, n)
        if n:
            total_seconds += est["total_seconds"]
            total_tokens += est["total_tokens"]
            any_estimate = True
        mark = "" if est["measured"] else "~"
        if n and not est["measured"]:
            any_guess = True
        dur = (f"{mark}{_secs(est['seconds'])} ×{n}" if n else "—")
        rows.append((f"{role} → {b.spec}", weight_glyph(b.model),
                     dur, WEIGHT_WORDS[weight_of(b.model)]))

    share = budget_footprint(total_tokens, cfg) if any_estimate else None
    # Korean labels and ● glyphs are wide characters: pad by display cells,
    # not by len(), or every column after the first drifts.
    width = max([ui.cell_width(r[0]) for r in rows] + [ui.cell_width("확정 바인딩")])
    lines = [f"  {ui.pad('확정 바인딩', width)}  무게   "
             f"{ui.pad('예상 소요', 14)} 등급"]
    for label, glyph, dur, word in rows:
        lines.append(f"  {ui.pad(label, width)}  {glyph}   "
                     f"{ui.pad(dur, 14)} {word}")

    if any_estimate:
        lines.append("  " + "─" * (width + 26))
        tilde = "~" if any_guess else ""
        tail = (f"  {ui.pad('합계', width)}  예상 {tilde}{_secs(total_seconds)} · "
                f"에이전트 {sum(counts.values())}")
        if share is not None:
            tail += f" · 일일 예산의 ~{share * 100:.0f}%"
        lines.append(tail)
        if share is not None and share >= 1.0:
            lines.append(f"  {ui.YELLOW}남은 일일 토큰 예산을 넘길 수 있습니다 "
                         f"— 중간에 멈출 수 있어요.{ui.RESET}")
    return "\n".join(lines)


def _secs(value: float) -> str:
    if value < 60:
        return f"{value:.0f}초"
    minutes, seconds = divmod(int(value), 60)
    return f"{minutes}분 {seconds}초" if seconds else f"{minutes}분"


# -- interactive selection -------------------------------------------------

def choose(roles: dict[str, dict], resolved: dict[str, Binding], *,
           cfg: dict, last: Optional[dict[str, str]] = None
           ) -> Optional[dict[str, str]]:
    """Ask, role by role, which model should run it.

    Returns the picked specs, or None if the user cancelled. Non-interactive
    terminals never reach here (the caller checks), and menu.select falls back
    to a numbered prompt anyway.
    """
    last = last or {}
    picked: dict[str, str] = {}
    for role, decl in roles.items():
        current = resolved[role]
        options: list[tuple[str, str]] = []
        seen: set[str] = set()

        def offer(spec: str, note: str) -> None:
            if spec and spec not in seen:
                seen.add(spec)
                options.append((spec, note))

        offer(current.spec, f"그대로 [{current.source_label}]")
        offer(last.get(role, ""), "지난번")
        offer(str(decl.get("default") or ""), "스크립트 기본")
        hint = str(decl.get("hint") or "")
        title = f"{role}" + (f" — {hint}" if hint else "")

        labels = [f"{spec:<28} {note}" for spec, note in options]
        labels.append("다른 모델 고르기…")
        index = menu.select(title, labels, default=0)
        if index is None:
            return None
        if index < len(options):
            picked[role] = options[index][0]
            continue
        chosen = _browse(cfg)
        if chosen is None:
            return None
        picked[role] = chosen
    return picked


def _browse(cfg: dict) -> Optional[str]:
    """Provider, then model — reusing the same discovery `birkin model` uses."""
    providers_available = ["codex", "claude", "anthropic", "openai", "local"]
    pindex = menu.select("프로바이더", providers_available, default=0)
    if pindex is None:
        return None
    provider = providers_available[pindex]

    choices = _models_for(provider, cfg)
    if not choices:
        return provider                      # provider default model
    choices = choices + ["(직접 입력)"]
    mindex = menu.select(f"{provider} 모델", choices, default=0)
    if mindex is None:
        return None
    if mindex == len(choices) - 1:
        try:
            typed = input("  모델 이름: ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        return f"{provider}:{typed}" if typed else provider
    return f"{provider}:{choices[mindex]}"


def _models_for(provider: str, cfg: dict) -> list[str]:
    if provider == "codex":
        try:
            return list(models.codex_model_ids(cfg))
        except Exception:
            return ["gpt-5.6-sol"]
    if provider == "claude":
        return ["sonnet", "opus", "haiku"]
    try:
        found = models.discover(cfg, api=True, cli=False, ollama=(provider == "local"))
    except Exception:
        return []
    return [m.model_value() for m in found][:20]


def confirm(prompt: str = "이대로 실행할까요?") -> str:
    """Y / n / s(저장). Anything unreadable means no."""
    try:
        answer = input(f"\n{prompt} [Y/n/저장(s)] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return "n"
    if answer in ("s", "save", "저장"):
        return "s"
    return "n" if answer in ("n", "no", "아니오") else "y"


def save_bindings(bindings: dict[str, Binding], cfg: dict) -> None:
    """Persist the picks as the user's standing default (ladder rung 5)."""
    from .. import config
    saved = config.load_config()
    roles = dict(saved.get("moirai_roles") or {})
    roles.update(B.as_specs(bindings))
    saved["moirai_roles"] = roles
    config.save_config(saved)
