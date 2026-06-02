"""Blind A/B model comparison — run one prompt through two models, hide which
is which until you pick.

A lightweight take on odysseus's "Compare": no eval harness, just two one-shot
completions presented blind (randomized A/B) so you judge the output, not the
brand. Stays free on the subscription path (e.g. opus vs sonnet vs haiku).

Pure standard library. The runner takes an ``ask(model) -> text`` callable so it
is decoupled from any client (and testable); the default builds a one-shot
client from cfg.
"""

from __future__ import annotations

import random
from typing import Any, Callable, Optional

from . import config


def _ask_via_client(cfg: dict[str, Any], prompt: str, model: str) -> str:
    from .llm import build_client
    client = build_client(cfg, config.get_api_key(cfg))
    messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
    try:
        res = client.complete(system="", messages=messages, tools=[], model=model)
    except Exception as exc:
        return f"[birkin] {model} error: {exc}"
    return "".join(b.get("text", "") for b in res.get("content", [])
                   if b.get("type") == "text").strip()


def run(cfg: dict[str, Any], prompt: str, model_a: str, model_b: str, *,
        ask: Optional[Callable[[str], str]] = None,
        shuffle: bool = True) -> dict[str, Any]:
    """Run ``prompt`` through ``model_a`` and ``model_b``; return a blind result.

    Returns ``{"prompt", "A": {model, text}, "B": {model, text}}`` where A/B are
    randomized (``shuffle``) so the labels don't reveal the model. ``ask`` is
    ``callable(model) -> text`` (default: a one-shot client built from ``cfg``).
    """
    ask = ask or (lambda m: _ask_via_client(cfg, prompt, m))
    pair = [(model_a, ask(model_a)), (model_b, ask(model_b))]
    if shuffle:
        random.shuffle(pair)
    return {"prompt": prompt,
            "A": {"model": pair[0][0], "text": pair[0][1]},
            "B": {"model": pair[1][0], "text": pair[1][1]}}


def default_pair(cfg: dict[str, Any], a: Optional[str], b: Optional[str]
                 ) -> tuple[str, str]:
    """Resolve the two models to compare from flags + the current config."""
    a = a or cfg.get("model") or "opus"
    if b:
        return a, b
    # pick a complementary tier so the default compare isn't a model vs itself
    fallback = "sonnet" if a not in ("sonnet",) else "haiku"
    return a, fallback
