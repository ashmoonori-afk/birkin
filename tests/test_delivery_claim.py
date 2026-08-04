"""At-most-once delivery: a claim, an attempt counter, and stale recovery.

delivery.py records an obligation before a send and clears it after, so a
gateway crash between "reply produced" and "reply sent" redelivers instead of
losing the answer. That part works.

What it could not do is survive TWO daemons. `redeliver()` read every pending
row and sent it, so a second gateway process booting at the same time sent the
same backlog again -- the duplicate the module's docstring accepts as the price
of durability became a duplicate per running process. There was also no attempt
counter, so a row that can never be delivered (a chat the bot was removed from)
was retried on every boot forever with nothing recording that it kept failing.

hermes solves this with delivery_state / delivery_attempts / delivery_claim /
delivery_claimed_at on its async_delegations table. Same contract here.
"""

from __future__ import annotations

import sqlite3

import pytest

from birkin import config, delivery


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    return tmp_path


class TestExistingContractUnchanged:
    """Characterization: green before the claim ledger, green after."""

    def test_record_then_pending_then_clear(self, home) -> None:
        rid = delivery.record("telegram", "42", "hello")
        assert rid is not None
        rows = delivery.pending("telegram")
        assert [r["text"] for r in rows] == ["hello"]
        delivery.clear(rid)
        assert delivery.pending("telegram") == []

    def test_empty_text_is_not_recorded(self, home) -> None:
        assert delivery.record("telegram", "42", "   ") is None

    def test_pending_is_scoped_by_channel(self, home) -> None:
        delivery.record("telegram", "1", "a")
        delivery.record("slack", "2", "b")
        assert [r["text"] for r in delivery.pending("telegram")] == ["a"]


class TestClaimPreventsDoubleDelivery:
    def test_claim_returns_the_pending_rows(self, home) -> None:
        delivery.record("telegram", "1", "a")
        delivery.record("telegram", "2", "b")
        claimed = delivery.claim("telegram", owner="daemon-1")
        assert [r["text"] for r in claimed] == ["a", "b"]

    def test_a_second_owner_claims_nothing(self, home) -> None:
        """The exact duplicate-delivery case: two daemons booting together."""
        delivery.record("telegram", "1", "a")
        first = delivery.claim("telegram", owner="daemon-1")
        second = delivery.claim("telegram", owner="daemon-2")
        assert len(first) == 1
        assert second == []

    def test_claimed_rows_are_no_longer_offered_to_claim(self, home) -> None:
        delivery.record("telegram", "1", "a")
        delivery.claim("telegram", owner="daemon-1")
        assert delivery.claim("telegram", owner="daemon-1") == []

    def test_claim_is_scoped_by_channel(self, home) -> None:
        delivery.record("telegram", "1", "a")
        delivery.record("slack", "2", "b")
        assert [r["channel"] for r in delivery.claim("telegram", owner="d")] \
            == ["telegram"]

    def test_pending_still_reports_a_claimed_row(self, home) -> None:
        """A claim is not a discharge: only clear() removes the obligation."""
        rid = delivery.record("telegram", "1", "a")
        delivery.claim("telegram", owner="daemon-1")
        assert [r["id"] for r in delivery.pending("telegram")] == [rid]


class TestAttemptCounter:
    def test_attempts_start_at_zero(self, home) -> None:
        delivery.record("telegram", "1", "a")
        assert delivery.claim("telegram", owner="d")[0]["delivery_attempts"] == 0

    def test_each_claim_counts_an_attempt(self, home) -> None:
        delivery.record("telegram", "1", "a")
        delivery.claim("telegram", owner="d")
        rows = delivery.claim("telegram", owner="d", stale_after=0.0)
        assert rows[0]["delivery_attempts"] == 1

    def test_attempts_survive_in_pending(self, home) -> None:
        delivery.record("telegram", "1", "a")
        delivery.claim("telegram", owner="d")
        assert delivery.pending("telegram")[0]["delivery_attempts"] == 1


class TestStaleClaimRecovery:
    def test_a_crashed_claimer_does_not_wedge_the_row(self, home) -> None:
        """Without expiry a daemon that dies mid-send loses the reply for good."""
        delivery.record("telegram", "1", "a")
        delivery.claim("telegram", owner="dead-daemon")
        recovered = delivery.claim("telegram", owner="new-daemon", stale_after=0.0)
        assert [r["text"] for r in recovered] == ["a"]

    def test_a_fresh_claim_is_respected(self, home) -> None:
        delivery.record("telegram", "1", "a")
        delivery.claim("telegram", owner="live-daemon")
        assert delivery.claim("telegram", owner="other",
                              stale_after=3600.0) == []


class TestRedeliverUsesTheClaim:
    def test_two_daemons_send_the_reply_once(self, home) -> None:
        delivery.record("telegram", "1", "a")
        sent_a: list[str] = []
        sent_b: list[str] = []
        n_a = delivery.redeliver("telegram", lambda c, t: sent_a.append(t) or True,
                                 owner="daemon-a")
        n_b = delivery.redeliver("telegram", lambda c, t: sent_b.append(t) or True,
                                 owner="daemon-b")
        assert (n_a, n_b) == (1, 0)
        assert len(sent_a) == 1 and sent_b == []

    def test_a_refused_send_leaves_the_obligation_recorded(self, home) -> None:
        delivery.record("telegram", "1", "a")
        assert delivery.redeliver("telegram", lambda c, t: False,
                                  owner="d") == 0
        assert len(delivery.pending("telegram")) == 1

    def test_a_successful_send_clears_the_row(self, home) -> None:
        delivery.record("telegram", "1", "a")
        assert delivery.redeliver("telegram", lambda c, t: True, owner="d") == 1
        assert delivery.pending("telegram") == []


class TestSchemaMigration:
    def test_an_existing_outbox_without_the_new_columns_is_upgraded(
            self, home) -> None:
        """A user's delivery.db predates the claim ledger; it must not break."""
        path = config.birkin_home() / "delivery.db"
        con = sqlite3.connect(path)
        con.executescript(
            "CREATE TABLE outbox (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " channel TEXT NOT NULL, chat_id TEXT NOT NULL,"
            " text TEXT NOT NULL, created TEXT NOT NULL);")
        con.execute("INSERT INTO outbox (channel, chat_id, text, created)"
                    " VALUES ('telegram', '9', 'old reply', '2026-01-01')")
        con.commit()
        con.close()

        rows = delivery.pending("telegram")
        assert [r["text"] for r in rows] == ["old reply"]
        assert rows[0]["delivery_attempts"] == 0
        assert [r["text"] for r in delivery.claim("telegram", owner="d")] \
            == ["old reply"]
