"""Role → model bindings: who runs each agent, decided before the run starts.

A workflow script says *what* to do; a binding says *who* does it. Keeping them
apart is what lets the same script run cheap once and expensive once without
editing a line — and it is why a script declares ``roles`` instead of hardcoding
a provider.

Resolution ladder, highest wins (design §4b):

1. the script's explicit ``provider=``/``model=`` on that one call
2. ``--bind role=provider:model`` on the command line
3. whatever the interactive picker chose
4. the bindings the last run of this script used
5. ``moirai_roles`` in config — the user's standing preference
6. the script's own ``meta["roles"][role]["default"]``
7. the global provider/model, for a script that declares no roles

Everything here is pure: the ladder takes dicts in and gives a dict out, so the
picker, the CLI and the tests all exercise the same code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# Providers a binding may name. "claude"/"codex" are the CLI agents; the rest
# are API paths. Kept in sync with providers.get_completer's dispatch.
KNOWN_PROVIDERS = ("claude", "codex", "anthropic", "openai", "gemini", "local")

# Where a binding came from — shown in the picker so the user can see whether a
# value is theirs, the script author's, or a leftover.
SOURCE_LABELS = {
    "call": "스크립트 명시",
    "cli": "--bind",
    "picker": "선택",
    "last": "지난번",
    "config": "내 기본값",
    "meta": "스크립트 기본",
    "global": "전역 설정",
}


class BindingError(ValueError):
    """A binding that cannot be honored — raised before any agent runs."""


@dataclass(frozen=True)
class Binding:
    role: str
    provider: str
    model: str
    source: str            # one of SOURCE_LABELS
    tools: str = "none"    # "none" | "read-only" | "workspace"

    @property
    def spec(self) -> str:
        return f"{self.provider}:{self.model}"

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)


def parse_spec(spec: str) -> tuple[str, str]:
    """``"codex:gpt-5.6-sol"`` -> ``("codex", "gpt-5.6-sol")``.

    A bare provider (``"codex"``) means "that provider, its default model" and
    yields an empty model, which the provider layer resolves.
    """
    text = (spec or "").strip()
    if not text:
        raise BindingError("빈 바인딩")
    provider, sep, model = text.partition(":")
    provider = provider.strip().lower().removesuffix("-cli")
    model = model.strip() if sep else ""
    if not provider:
        raise BindingError(f"프로바이더가 없습니다: {spec!r}")
    return provider, model


def parse_cli_binds(pairs: list[str] | None) -> dict[str, str]:
    """``["critic=claude:opus"]`` -> ``{"critic": "claude:opus"}``."""
    out: dict[str, str] = {}
    for raw in pairs or []:
        role, sep, spec = str(raw).partition("=")
        if not sep or not role.strip() or not spec.strip():
            raise BindingError(
                f"--bind 형식은 role=provider:model 입니다: {raw!r}")
        out[role.strip()] = spec.strip()
    return out


def declared_roles(meta: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The script's ``meta["roles"]``, normalized to dicts.

    A role may be declared as a bare spec string for brevity:
    ``"roles": {"critic": "claude:haiku"}``.
    """
    raw = (meta or {}).get("roles") or {}
    if not isinstance(raw, dict):
        raise BindingError("meta['roles']는 dict여야 합니다")
    out: dict[str, dict[str, Any]] = {}
    for role, value in raw.items():
        name = str(role).strip()
        if not name:
            raise BindingError("빈 role 이름")
        if isinstance(value, str):
            out[name] = {"default": value}
        elif isinstance(value, dict):
            out[name] = dict(value)
        else:
            raise BindingError(
                f"role {name!r} 선언은 문자열이나 dict여야 합니다")
    return out


def resolve(
    roles: dict[str, dict[str, Any]],
    *,
    cli: Optional[dict[str, str]] = None,
    picked: Optional[dict[str, str]] = None,
    last: Optional[dict[str, str]] = None,
    cfg: Optional[dict[str, Any]] = None,
) -> dict[str, Binding]:
    """Walk the ladder for every declared role. Pure — no I/O, no prompting."""
    cfg = cfg or {}
    config_roles = cfg.get("moirai_roles") or {}
    global_spec = _global_spec(cfg)

    out: dict[str, Binding] = {}
    for role, decl in roles.items():
        spec, source = None, ""
        for candidate, src in (
            ((cli or {}).get(role), "cli"),
            ((picked or {}).get(role), "picker"),
            ((last or {}).get(role), "last"),
            (config_roles.get(role), "config"),
            (decl.get("default"), "meta"),
            (global_spec, "global"),
        ):
            if candidate:
                spec, source = str(candidate), src
                break
        if not spec:
            raise BindingError(
                f"role {role!r}에 바인딩할 모델이 없습니다 — "
                f"meta default나 --bind를 주세요")
        provider, model = parse_spec(spec)
        out[role] = Binding(role=role, provider=provider, model=model,
                            source=source,
                            tools=str(decl.get("tools", "none")))
    return out


def _global_spec(cfg: dict[str, Any]) -> str:
    provider = str(cfg.get("provider") or "").removesuffix("-cli")
    model = str(cfg.get("model") or "")
    if not provider:
        return ""
    return f"{provider}:{model}" if model else provider


# -- validation ------------------------------------------------------------

def validate(bindings: dict[str, Binding], cfg: Optional[dict] = None) -> None:
    """Reject impossible bindings *before* the first agent spawns.

    A wrong model discovered by the eighth agent is a 400 forty seconds in;
    discovered here it is a message and an exit code.
    """
    cfg = cfg or {}
    for b in bindings.values():
        if b.provider not in KNOWN_PROVIDERS:
            raise BindingError(
                f"role {b.role!r}: 모르는 프로바이더 {b.provider!r} "
                f"(가능: {', '.join(KNOWN_PROVIDERS)})")
        if b.tools not in ("none", "read-only", "workspace"):
            raise BindingError(
                f"role {b.role!r}: tools는 none|read-only|workspace 입니다 "
                f"— {b.tools!r}")
        _validate_model(b, cfg)


def _validate_model(b: Binding, cfg: dict) -> None:
    """Per-provider model legality, reusing the gateway's family check.

    A claude alias handed to codex (or a gpt id handed to claude) is the
    mistake this catches — it 400s at turn one otherwise.
    """
    if not b.model:
        return                                  # provider default: fine
    name = b.model.lower()
    if b.provider == "codex":
        if name.startswith("claude") or name in ("opus", "sonnet", "haiku"):
            raise BindingError(
                f"role {b.role!r}: {b.model!r}는 claude 계열 이름입니다 — "
                f"codex에 배정할 수 없습니다")
        from .. import codex_session
        if not codex_session._MODEL_RE.fullmatch(b.model):
            raise BindingError(
                f"role {b.role!r}: codex 모델 이름에 쓸 수 없는 문자 "
                f"— {b.model!r}")
    elif b.provider == "claude":
        if name.startswith(("gpt", "codex", "o3", "o4")):
            raise BindingError(
                f"role {b.role!r}: {b.model!r}는 codex/OpenAI 계열 이름입니다 "
                f"— claude에 배정할 수 없습니다")


def check_roles_used(roles: dict[str, dict], used: set[str]) -> None:
    """A ``role=`` the script uses but never declared is a typo, caught once."""
    unknown = sorted(used - set(roles))
    if unknown:
        raise BindingError(
            f"선언되지 않은 role 참조: {', '.join(unknown)} — "
            f"meta['roles']에 추가하세요")


def as_specs(bindings: dict[str, Binding]) -> dict[str, str]:
    """Flatten for the journal / config, so the next run can offer '지난번'."""
    return {role: b.spec for role, b in bindings.items()}
