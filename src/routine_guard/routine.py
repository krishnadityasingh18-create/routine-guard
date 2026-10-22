"""Routine learning: fold events into a per-zone daily rhythm. Pure, no I/O.

Functions mutate the Routine in place and also return it.
- Late events for an already-closed local day are ignored.
- The window is the last D *active* days: a day without activity in a zone is not a sample
  of when that zone is used.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from statistics import median
from zoneinfo import ZoneInfo

from routine_guard.models import Config, Event, Routine

SLOTS_PER_DAY = 96
SLOT_MINUTES = 15
HISTORY_DAYS = 14  # D


def new_routine(source: str, zone: str) -> Routine:
    """Empty routine. O(1)."""
    return Routine(source, zone, [0] * SLOTS_PER_DAY, 0, [], None, None, None, None, None, set())


def counts(e: Event, cfg: Config) -> bool:
    return cfg.activity_types is None or e.type in cfg.activity_types


def update(r: Routine, e: Event, cfg: Config) -> Routine:
    """Fold one event into today's accumulators. O(1), plus a once-a-day rollover."""
    if not counts(e, cfg):
        return r
    t = e.ts.astimezone(ZoneInfo(cfg.tz))
    day, minute = t.date(), t.hour * 60 + t.minute
    if r.today is None:
        r.today = day
    elif day > r.today:
        rollover(r, day)
    elif day < r.today:
        return r
    r.today_slots.add(minute // SLOT_MINUTES)
    if r.today_first is None or minute < r.today_first:
        r.today_first = minute
    if r.last_event_ts is None or e.ts > r.last_event_ts:
        r.last_event_ts = e.ts
    return r


def rollover(r: Routine, new_day: date) -> Routine:
    """Close `r.today` into the window and start `new_day`. O(D log D). No-op going back."""
    if r.today is not None and new_day <= r.today:
        return r
    if r.today_slots:
        slots = sorted(r.today_slots)
        for s in slots:
            r.hist[s] += 1
        r.day_slots.append(slots)
        r.first_times.append(r.today_first)  # type: ignore[arg-type]
        if len(r.day_slots) > HISTORY_DAYS:
            for s in r.day_slots.pop(0):
                r.hist[s] -= 1
            r.first_times.pop(0)
        r.days_seen = len(r.day_slots)
        med = int(median(r.first_times))
        r.median_first = med
        r.mad_first = int(median(abs(x - med) for x in r.first_times))
    r.today, r.today_first, r.today_slots = new_day, None, set()
    return r


def learn(events, cfg: Config) -> dict[tuple[str, str], Routine]:
    """Replay history oldest-first into routines keyed by (source, zone). O(n log n)."""
    routines: dict[tuple[str, str], Routine] = {}
    for e in sorted(events, key=lambda ev: ev.ts):
        key = (e.source, e.zone)
        if key not in routines:
            routines[key] = new_routine(e.source, e.zone)
        update(routines[key], e, cfg)
    return routines


def to_dict(r: Routine) -> dict:
    """JSON-safe dict (ints, lists, ISO strings; no floats). O(D + slots)."""
    return {
        "source": r.source,
        "zone": r.zone,
        "hist": list(r.hist),
        "days_seen": r.days_seen,
        "first_times": list(r.first_times),
        "median_first": r.median_first,
        "mad_first": r.mad_first,
        "last_event_ts": r.last_event_ts.astimezone(UTC).isoformat() if r.last_event_ts else None,
        "today": r.today.isoformat() if r.today else None,
        "today_first": r.today_first,
        "today_slots": sorted(r.today_slots),
        "day_slots": [list(d) for d in r.day_slots],
        "fired": dict(r.fired),
    }


def from_dict(d: dict) -> Routine:
    """Inverse of `to_dict`; numbers may be Decimals (e.g. from DynamoDB)."""

    def opt(x):
        return None if x is None else int(x)

    return Routine(
        source=d["source"],
        zone=d["zone"],
        hist=[int(x) for x in d["hist"]],
        days_seen=int(d["days_seen"]),
        first_times=[int(x) for x in d.get("first_times") or []],
        median_first=opt(d.get("median_first")),
        mad_first=opt(d.get("mad_first")),
        last_event_ts=datetime.fromisoformat(d["last_event_ts"])
        if d.get("last_event_ts")
        else None,
        today=date.fromisoformat(d["today"]) if d.get("today") else None,
        today_first=opt(d.get("today_first")),
        today_slots={int(x) for x in d.get("today_slots") or []},
        day_slots=[[int(s) for s in day] for day in d.get("day_slots") or []],
        fired=dict(d.get("fired") or {}),
    )
