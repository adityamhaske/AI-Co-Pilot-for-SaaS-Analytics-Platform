"""Period spines.

Building the buckets in Python rather than in SQL keeps every generated query free of
dialect-specific date functions. The original implementation used ``strftime``, which
exists only in SQLite, so every trend query failed on PostgreSQL.
"""

import datetime
from typing import Literal, NamedTuple

Granularity = Literal["day", "week", "month"]

# One conditional aggregate is emitted per period, so the count is bounded to keep the
# generated SQL sane. 400 covers a year of daily points or three decades of monthly ones.
MAX_PERIODS = 400


class Period(NamedTuple):
    """A half-open bucket ``[start, end)`` with the label the user sees."""

    label: str
    start: datetime.date
    end: datetime.date


def build_periods(
    start: datetime.date, end: datetime.date, granularity: Granularity
) -> list[Period]:
    """Split the inclusive range ``[start, end]`` into half-open buckets."""
    if end < start:
        raise ValueError("end_date must not be earlier than start_date")

    periods: list[Period] = []

    if granularity == "month":
        cursor = start.replace(day=1)

        def step(d: datetime.date) -> datetime.date:
            return (d.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)

        def label(d: datetime.date) -> str:
            return d.strftime("%Y-%m")

    elif granularity == "week":
        cursor = start - datetime.timedelta(days=start.weekday())  # ISO Monday

        def step(d: datetime.date) -> datetime.date:
            return d + datetime.timedelta(days=7)

        def label(d: datetime.date) -> str:
            return d.strftime("%Y-%m-%d")

    elif granularity == "day":
        cursor = start

        def step(d: datetime.date) -> datetime.date:
            return d + datetime.timedelta(days=1)

        def label(d: datetime.date) -> str:
            return d.strftime("%Y-%m-%d")

    else:
        raise ValueError(f"Unknown granularity: {granularity!r}")

    while cursor <= end:
        nxt = step(cursor)
        periods.append(Period(label(cursor), cursor, nxt))
        cursor = nxt
        if len(periods) > MAX_PERIODS:
            raise ValueError(
                f"That range needs more than {MAX_PERIODS} {granularity} buckets. "
                "Narrow the date range or use a coarser granularity."
            )

    return periods


def relative_period(
    period: Literal["last_month", "last_quarter", "last_year"],
    today: datetime.date | None = None,
) -> Period:
    """Resolve a named relative window into a concrete half-open period."""
    today = today or datetime.date.today()
    months = {"last_month": 1, "last_quarter": 3, "last_year": 12}.get(period)
    if months is None:
        raise ValueError(f"Unknown period: {period!r}")

    start = today
    for _ in range(months):
        start = (start.replace(day=1) - datetime.timedelta(days=1)).replace(
            day=min(today.day, 28)
        )

    return Period(period, start, today + datetime.timedelta(days=1))
