"""More than one credential for the same provider, rotated on a 429.

birkin already treats HTTP 429 as ``rate_limit`` (llm.py _kind_for_status),
already retries it with backoff, and already fails over to a *different*
provider once those retries are spent (FAILOVER_KINDS). What it could not do is
hold a second key for the SAME provider: an account that rate-limits burned the
retries and then answered from a different provider and a different model, when
the cheap correct move was the next key of the same account family.

Exhaustion is per credential and time-boxed, mirroring the cooldowns hermes
derives from the failing status (agent/credential_pool.py _exhausted_ttl): a 401
is likely a typo'd key worth retrying soon, a 429 is a quota window worth
waiting out.

The clock is injected everywhere, so nothing here sleeps.
"""

from __future__ import annotations

import pytest

from birkin import credpool
from birkin.llm import LLMError

K1, K2, K3 = "sk-ant-key-one", "sk-ant-key-two", "sk-ant-key-three"


class _Clock:
    """A hand-cranked monotonic clock. Cooldowns are tested, never waited on."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class TestCooldownDependsOnWhyItFailed:
    def test_a_bad_key_is_retried_sooner_than_a_quota_window(self) -> None:
        assert credpool.cooldown_for(401) < credpool.cooldown_for(429)

    def test_rate_limit_cools_down_for_an_hour(self) -> None:
        assert credpool.cooldown_for(429) == 3600.0

    def test_an_unknown_status_gets_the_conservative_default(self) -> None:
        assert credpool.cooldown_for(None) == credpool.cooldown_for(500) == 3600.0


class TestRotation:
    def test_the_first_key_is_used_until_it_fails(self) -> None:
        pool = credpool.CredentialPool([K1, K2])
        assert pool.current() == K1
        assert pool.current() == K1

    def test_a_rate_limited_key_rotates_to_the_next(self) -> None:
        clock = _Clock()
        pool = credpool.CredentialPool([K1, K2], now=clock)
        assert pool.mark_exhausted(K1, 429) == K2
        assert pool.current() == K2

    def test_rotation_walks_every_key_before_giving_up(self) -> None:
        clock = _Clock()
        pool = credpool.CredentialPool([K1, K2, K3], now=clock)
        assert pool.mark_exhausted(K1, 429) == K2
        assert pool.mark_exhausted(K2, 429) == K3
        assert pool.mark_exhausted(K3, 429) is None
        assert pool.current() is None

    def test_a_cooled_down_key_becomes_available_again(self) -> None:
        clock = _Clock()
        pool = credpool.CredentialPool([K1], now=clock)
        assert pool.mark_exhausted(K1, 429) is None
        assert pool.current() is None
        clock.advance(credpool.cooldown_for(429) + 1)
        assert pool.current() == K1

    def test_a_cooldown_that_has_not_expired_is_respected(self) -> None:
        clock = _Clock()
        pool = credpool.CredentialPool([K1], now=clock)
        pool.mark_exhausted(K1, 429)
        clock.advance(credpool.cooldown_for(429) - 1)
        assert pool.current() is None

    def test_marking_an_unknown_key_does_not_exhaust_a_real_one(self) -> None:
        """A stale rotation must not cost a working credential."""
        pool = credpool.CredentialPool([K1, K2], now=_Clock())
        pool.mark_exhausted("sk-ant-not-in-the-pool", 429)
        assert pool.current() == K1

    def test_a_single_key_pool_is_still_a_pool(self) -> None:
        pool = credpool.CredentialPool([K1], now=_Clock())
        assert pool.current() == K1
        assert pool.depth == 1

    def test_duplicate_and_blank_keys_are_dropped(self) -> None:
        pool = credpool.CredentialPool([K1, "", K1, "  ", K2], now=_Clock())
        assert pool.depth == 2


class TestFromConfig:
    def test_an_api_keys_list_becomes_the_pool(self) -> None:
        pool = credpool.from_config({"provider": "anthropic",
                                     "api_keys": [K1, K2]}, K1)
        assert pool is not None and pool.depth == 2

    def test_one_key_needs_no_pool(self) -> None:
        """No list configured means nothing to rotate to -- stay out of the way."""
        assert credpool.from_config({"provider": "anthropic"}, K1) is None

    def test_the_resolved_key_leads_even_when_the_list_orders_it_late(self) -> None:
        """get_api_key already chose; the pool must not silently switch accounts."""
        pool = credpool.from_config({"api_keys": [K1, K2]}, K2)
        assert pool is not None and pool.current() == K2

    def test_a_resolved_key_absent_from_the_list_is_still_tried_first(self) -> None:
        pool = credpool.from_config({"api_keys": [K1, K2]}, K3)
        assert pool is not None and pool.current() == K3
        assert pool.depth == 3


class _Recorder:
    """A client stand-in that fails with the statuses a script hands it."""

    def __init__(self, api_key: str, script: list[object]) -> None:
        self.api_key = api_key
        self._script = script
        provider, model = "anthropic", "claude-sonnet-4-6"
        self.provider, self.model = provider, model

    def complete(self, **kwargs: object) -> dict[str, object]:
        outcome = self._script.pop(0) if self._script else "ok"
        if isinstance(outcome, tuple):
            kind, status = outcome
            raise LLMError(f"boom {status}", kind=kind, status=status)
        return {"role": "assistant", "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn", "used_key": self.api_key}


class TestRotatingClient:
    @staticmethod
    def _build(scripts: dict[str, list[object]]) -> tuple[object, list[str]]:
        seen: list[str] = []

        def factory(key: str) -> object:
            seen.append(key)
            return _Recorder(key, list(scripts.get(key, [])))

        pool = credpool.CredentialPool(list(scripts), now=_Clock())
        return credpool.RotatingClient(pool, factory), seen

    def test_a_rate_limit_retries_on_the_next_credential(self) -> None:
        client, seen = self._build({K1: [("rate_limit", 429)], K2: ["ok"]})
        assert client.complete()["used_key"] == K2
        assert seen == [K1, K2]

    def test_a_working_credential_is_not_rotated_away(self) -> None:
        client, seen = self._build({K1: ["ok"], K2: ["ok"]})
        assert client.complete()["used_key"] == K1
        assert seen == [K1]

    def test_an_exhausted_pool_raises_the_real_error(self) -> None:
        client, _ = self._build({K1: [("rate_limit", 429)],
                                 K2: [("rate_limit", 429)]})
        with pytest.raises(LLMError) as caught:
            client.complete()
        assert caught.value.kind == "rate_limit"

    def test_an_error_a_second_key_cannot_fix_is_not_rotated_on(self) -> None:
        """An oversized request fails identically on every credential."""
        client, seen = self._build({K1: [("overflow", 400)], K2: ["ok"]})
        with pytest.raises(LLMError):
            client.complete()
        assert seen == [K1]

    def test_attributes_report_the_answering_client(self) -> None:
        client, _ = self._build({K1: ["ok"]})
        assert client.provider == "anthropic"
        assert client.model == "claude-sonnet-4-6"

    def test_settings_written_mid_session_reach_the_rotated_client(self) -> None:
        """The failover wrapper had this bug shape; a rotation must not lose it."""
        client, _ = self._build({K1: [("rate_limit", 429)], K2: ["ok"]})
        client.cli_access = True
        client.complete()
        assert client.cli_access is True
