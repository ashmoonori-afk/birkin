"""Crontab expression spellings, normalized to what the matcher understands.

:mod:`birkin.cron` owns job storage and firing; this module owns the *grammar*
of a 5-field expression. Splitting them keeps cron.py from growing a second
responsibility, and keeps this file small enough to read in one sitting.

Every spelling handled here previously **parsed, saved, and then never fired** --
the worst failure mode a scheduler has, because nothing reports it:

* ``7`` for Sunday. POSIX accepts 0 and 7; the matcher compares against
  ``isoweekday() % 7``, which is never 7, so the job sat there forever.
* ``MON`` / ``JAN`` name aliases, which standard crontabs accept.
* ``@daily`` and friends.

Unknown names are refused outright, so a typo fails at creation instead of
becoming a job that silently does nothing.
"""

from __future__ import annotations

import re


FIELD_RE = re.compile(r"^[\d*,/-]+$")

_MACROS = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}
_DOW_NAMES = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3,
              "THU": 4, "FRI": 5, "SAT": 6}
_MONTH_NAMES = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
                "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
_NAME_RE = re.compile(r"[A-Za-z]+")


def _substitute_names(field: str, names: dict[str, int]) -> str | None:
    """``MON-FRI`` -> ``1-5``. None when the field names a day/month nothing has."""
    unknown: list[str] = []

    def one(match: re.Match[str]) -> str:
        value = names.get(match.group(0).upper())
        if value is None:
            unknown.append(match.group(0))
            return match.group(0)
        return str(value)

    out = _NAME_RE.sub(one, field)
    return None if unknown else out


def sunday_as_zero(field: str) -> str:
    """Fold POSIX's second spelling of Sunday onto the 0 the matcher compares.

    A bare ``7`` becomes ``0``. A range *ending* at 7 (``1-7`` is Mon..Sun)
    becomes ``1-6,0``, because rewriting it to ``1-0`` would be a reversed
    range that matches nothing.
    """
    parts: list[str] = []
    for part in field.split(","):
        base, sep, raw_step = part.partition("/")
        head, range_sep, tail = base.partition("-")
        if range_sep and tail == "7" and head.isdigit():
            start = int(head)
            folded = "0-6" if start == 0 else f"{start}-6"
            parts.append(folded + (f"/{raw_step}" if sep else ""))
            if start != 0:
                parts.append("0")
            continue
        if base == "7":
            parts.append("0")
            continue
        parts.append(part)
    return ",".join(parts)


def normalize(text: str) -> str | None:
    """Five cron fields the matcher can evaluate, or None when ``text`` is not one.

    Callers use the None to fall through to another schedule shape, so this must
    stay quiet about non-cron input rather than raising.
    """
    text = (text or "").strip()
    macro = _MACROS.get(text.lower())
    if macro:
        return macro
    fields = text.split()
    if len(fields) != 5:
        return None
    minute_f, hour_f, dom_f, month_f, dow_f = fields[:5]
    month_f = _substitute_names(month_f, _MONTH_NAMES)
    dow_f = _substitute_names(dow_f, _DOW_NAMES)
    if month_f is None or dow_f is None:
        return None
    expr = " ".join([minute_f, hour_f, dom_f, month_f,
                     sunday_as_zero(dow_f)])
    if not all(FIELD_RE.match(f) for f in expr.split()):
        return None
    return expr
