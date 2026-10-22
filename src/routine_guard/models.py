"""Data model: events in, routines learned, anomalies out."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(slots=True)
class Event:
    """One timestamped observation from a stream (a sensor, a device, a server...)."""

    id: str
    source: str  # what is being watched: a home, a person, a host
    zone: str  # where/what within the source: "kitchen", "front_door", "api"
    ts: datetime  # timezone-aware
    type: str = "activity"


@dataclass(slots=True)
class Routine:
    """Learned daily rhythm of one (source, zone): 96 slots of 15 minutes over the last D days."""

    source: str
    zone: str
    hist: list[int]  # per slot: number of days (in the window) with activity in that slot
    days_seen: int  # active days in the window (<= D)
    first_times: list[int]  # first-activity minute-of-day per active day, oldest first
    median_first: int | None
    mad_first: int | None  # median absolute deviation of first_times
    last_event_ts: datetime | None
    today: date | None  # local day being accumulated
    today_first: int | None
    today_slots: set[int]
    day_slots: list[list[int]] = field(default_factory=list)  # closed days' slots, oldest first
    fired: dict[str, str] = field(default_factory=dict)  # anomaly kind -> local ISO date


@dataclass(slots=True)
class Anomaly:
    source: str
    kind: str  # "late_start" | "long_inactivity" | "night_activity"
    zone: str | None  # None for source-wide checks (long_inactivity)
    reason: str  # one human sentence, local 24h times
    detected_at: datetime
    details: dict


@dataclass(slots=True)
class Config:
    """Thresholds. Defaults suit a person's day at home; tune for other streams."""

    tz: str = "UTC"
    late_buffer_min_floor: int = 30  # minutes added to the usual first time, at least
    mad_multiplier: float = 3.0
    inactivity_minutes: int = 240
    waking_start: str = "06:00"  # "active hours": inactivity checked inside, night outside
    waking_end: str = "22:00"
    night_rare_ratio: float = 0.05
    min_days_for_checks: int = 5
    default_first_activity: str = "08:00"
    activity_types: frozenset[str] | None = None  # None: every event type counts
    night_zones: frozenset[str] | None = None  # None: night check on every zone
    cold_start_zones: frozenset[str] = frozenset()  # late_start before min_days, vs default
    late_start_zones: frozenset[str] | None = None  # None: every zone; e.g. {"kitchen", "bedroom"}
