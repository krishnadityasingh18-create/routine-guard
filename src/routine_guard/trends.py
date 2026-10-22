"""Weekly trend line from a routine's first-activity history. Pure."""

from __future__ import annotations

from statistics import median

from routine_guard.models import Routine

MIN_SHIFT = 30  # minutes
MIN_PREVIOUS_DAYS = 5


def weekly_trend(routine: Routine) -> str | None:
    """Median first activity of the last 7 active days vs the 7 before. O(D log D).

    Returns e.g. "Waking about 40 minutes later this week", or None if the shift is < 30 min
    or there are fewer than 7 + 5 days of history.
    """
    ft = routine.first_times
    last, prev = ft[-7:], ft[:-7][-7:]
    if len(last) < 7 or len(prev) < MIN_PREVIOUS_DAYS:
        return None
    shift = median(last) - median(prev)
    if abs(shift) < MIN_SHIFT:
        return None
    minutes = int(5 * round(abs(shift) / 5))
    what = (
        "Waking"
        if routine.zone == "bedroom"
        else f"First {routine.zone.replace('_', ' ')} activity"
    )
    return f"{what} about {minutes} minutes {'later' if shift > 0 else 'earlier'} this week"
