"""Moirai — deterministic multi-agent workflows across claude, codex and APIs.

Public surface:

    from birkin import moirai
    script = moirai.load_script("~/.birkin/moirai/scripts/review.py")
    moirai.run_script(script, args={"diff": ...})

Design: docs/moirai-design.md.
"""

from __future__ import annotations

from .bindings import (Binding, BindingError, as_specs, declared_roles,
                       parse_cli_binds, parse_spec, resolve, validate)
from .engine import (MoiraiAPI, MoiraiError, Run, Script, load_script,
                     run_script)

__all__ = [
    "Binding", "BindingError", "MoiraiAPI", "MoiraiError", "Run", "Script",
    "as_specs", "declared_roles", "load_script", "parse_cli_binds",
    "parse_spec", "resolve", "run_script", "validate",
]
