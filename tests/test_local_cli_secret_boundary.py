from __future__ import annotations

import os
import sys
from typing import final

import pytest

from birkin import secrets
from birkin.llm import LLMClient


@final
class _LocalClient(LLMClient):
    def run_local_cli(self) -> str:
        return self._run_local_cli("", None)


def _client(*, allowed: list[str] | None = None) -> _LocalClient:
    return _LocalClient(
        provider="local-cli",
        model="",
        api_key="",
        base_url="",
        cli_command=[
            sys.executable,
            "-c",
            "import os; print('\\n'.join(f'{k}={v}' for k, v in sorted(os.environ.items())))",
        ],
        cli_secret_env=allowed or [],
    )


def test_local_cli_denies_managed_secret_but_keeps_unrelated_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    managed = "BIRKIN_C038_SYNTHETIC_SECRET"
    unrelated = "BIRKIN_C038_UNRELATED_SENTINEL"
    monkeypatch.setenv(unrelated, "VISIBLE")
    _ = secrets.apply_all({
        "secrets": {
            managed: {
                "source": "command",
                "argv": [sys.executable, "-c", "print('SYNTHETIC-CHILD-LEAK')"],
            }
        }
    })

    child = secrets.local_cli_environment()
    surface = _client().run_local_cli()

    assert managed not in child
    assert child[unrelated] == "VISIBLE"
    assert f"{unrelated}=VISIBLE" in surface
    assert managed not in surface
    assert os.environ[managed] == "SYNTHETIC-CHILD-LEAK"


def test_local_cli_explicitly_opts_in_only_required_managed_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MANAGED_REQUIRED", "required")
    monkeypatch.setenv("MANAGED_OTHER", "other")
    _ = secrets.apply_all({
        "secrets": {
            "MANAGED_REQUIRED": {
                "source": "command",
                "argv": [sys.executable, "-c", "print('unused')"],
            },
            "MANAGED_OTHER": {
                "source": "command",
                "argv": [sys.executable, "-c", "print('unused')"],
            },
        }
    })

    child = secrets.local_cli_environment(["MANAGED_REQUIRED"])
    surface = _client(allowed=["MANAGED_REQUIRED"]).run_local_cli()

    assert child["MANAGED_REQUIRED"] == "required"
    assert "MANAGED_OTHER" not in child
    assert "MANAGED_REQUIRED=required" in surface
    assert "MANAGED_OTHER" not in surface
