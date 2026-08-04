"""The 5-field cron grammar: what it already guarantees, and what it missed.

birkin already parses `0 9 * * 1` (cron.py parse_schedule -> kind "cron") and
walks it with a bounded minute scan honouring vixie day-of-month/day-of-week
semantics. The tests in TestAlreadySupported pin that behaviour so the gap
fixes below cannot quietly regress it.

The gaps are the spellings POSIX cron accepts that birkin silently swallowed:
a job stored with one of them parses, saves, and then never fires -- the worst
possible failure for a scheduler, because nothing reports it.
"""

from __future__ import annotations

from datetime import datetime

from birkin import cron


def _next(text: str, now: datetime) -> datetime | None:
    schedule = cron.parse_schedule(text)
    assert schedule is not None, f"parse_schedule({text!r}) returned None"
    nxt = cron.compute_next_run(schedule, None, now)
    return datetime.fromisoformat(nxt) if nxt else None


# A Wednesday, so every weekday assertion below has somewhere to move to.
NOW = datetime(2026, 8, 5, 12, 0)


class TestAlreadySupported:
    """Characterization: green before the gap fix, green after."""

    def test_numeric_weekday_monday(self) -> None:
        nxt = _next("0 9 * * 1", NOW)
        assert nxt == datetime(2026, 8, 10, 9, 0)
        assert nxt.isoweekday() == 1

    def test_step_field_every_quarter_hour(self) -> None:
        assert _next("*/15 * * * *", NOW) == datetime(2026, 8, 5, 12, 15)

    def test_day_of_month(self) -> None:
        assert _next("0 9 1 * *", NOW) == datetime(2026, 9, 1, 9, 0)

    def test_range_field(self) -> None:
        assert _next("0 9 * * 1-5", NOW) == datetime(2026, 8, 6, 9, 0)

    def test_list_field(self) -> None:
        assert _next("30 8,17 * * *", NOW) == datetime(2026, 8, 5, 17, 30)

    def test_other_schedule_kinds_are_untouched(self) -> None:
        assert cron.parse_schedule("09:00")["kind"] == "daily"
        assert cron.parse_schedule("every 30m")["kind"] == "interval"


class TestSundayAsSeven:
    """POSIX allows 0 AND 7 for Sunday. birkin compared against isoweekday()%7,
    so a field of `7` could never equal the computed 0 -- the job parsed, saved
    and never fired."""

    def test_seven_is_sunday(self) -> None:
        assert _next("0 9 * * 7", NOW) == datetime(2026, 8, 9, 9, 0)

    def test_zero_is_still_sunday(self) -> None:
        assert _next("0 9 * * 0", NOW) == datetime(2026, 8, 9, 9, 0)


class TestNameAliases:
    """`MON`, `SUN`, `JAN` are standard crontab spellings."""

    def test_weekday_name(self) -> None:
        assert _next("0 9 * * MON", NOW) == datetime(2026, 8, 10, 9, 0)

    def test_weekday_name_range_is_business_days(self) -> None:
        assert _next("0 9 * * MON-FRI", NOW) == datetime(2026, 8, 6, 9, 0)

    def test_weekday_name_is_case_insensitive(self) -> None:
        assert _next("0 9 * * sun", NOW) == datetime(2026, 8, 9, 9, 0)

    def test_month_name(self) -> None:
        assert _next("0 9 1 JAN *", NOW) == datetime(2027, 1, 1, 9, 0)


class TestMacros:
    def test_daily_macro(self) -> None:
        assert _next("@daily", NOW) == datetime(2026, 8, 6, 0, 0)

    def test_hourly_macro(self) -> None:
        assert _next("@hourly", NOW) == datetime(2026, 8, 5, 13, 0)

    def test_weekly_macro_is_sunday_midnight(self) -> None:
        assert _next("@weekly", NOW) == datetime(2026, 8, 9, 0, 0)


class TestUnfireableExpressionsAreRejected:
    """A schedule that can never fire must be refused when it is created, not
    accepted and then silently skipped forever."""

    def test_out_of_range_hour_is_refused(self) -> None:
        assert cron.parse_schedule("0 99 * * *") is None

    def test_out_of_range_minute_is_refused(self) -> None:
        assert cron.parse_schedule("99 9 * * *") is None

    def test_unknown_name_is_refused(self) -> None:
        assert cron.parse_schedule("0 9 * * FUNDAY") is None
