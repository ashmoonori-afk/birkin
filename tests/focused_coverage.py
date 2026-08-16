"""Keep the global coverage floor on full runs, not partial selections."""

from __future__ import annotations

from collections.abc import Sequence

import pytest


def _has_explicit_test_selection(args: Sequence[str]) -> bool:
    return any(
        argument.endswith(".py")
        or ".py::" in argument
        for argument in args
        if not argument.startswith("-")
    )


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_load_initial_conftests(
    early_config: pytest.Config,
    parser: object,
    args: list[str],
) -> object:
    _ = parser
    if _has_explicit_test_selection(args):
        early_config.known_args_namespace.cov_source = []
    return (yield)
