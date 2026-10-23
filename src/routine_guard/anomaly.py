"""Three explainable rules. late_start fires at most once per local day per zone,
long_inactivity once per day per source, night_activity up to 3 times a night, 30 min apart.
What fired is remembered in `Routine.fired` — persist routines after a check.

- late_start: no activity in a zone today by usual first time + max(3 x MAD, 30 min).
- long_inactivity: in active hours, nothing anywhere in the source for 4 h, counting the
  night only from the start of active hours.
- night_activity: activity outside active hours in a slot used on < 5% of learned days;
  again for a later rare event >= 30 min after the zone's previous one, max 3 a night.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from routine_guard.models import Anomaly, Config, Event, Routine
from routine_guard.routine import SLOT_MINUTES, counts


def check_event(r: Routine, e: Event, cfg: Config) -> Anomaly | None:
    """night_activity, checked against history before `e`. O(1)."""
    if not counts(e, cfg) or (cfg.night_zones is not None and e.zone not in cfg.night_zones):
        return None
    if r.days_seen < cfg.min_days_for_checks:
        return None
    t = e.ts.astimezone(ZoneInfo(cfg.tz))
    minute = t.hour * 60 + t.minute
    slot = minute // SLOT_MINUTES
    if _active(minute, cfg) or r.hist[slot] >= cfg.night_rare_ratio * r.days_seen:
        return None
    if not _claim_night(r, e.ts, _night_of(t.date(), minute, cfg), cfg):
        return None
    return Anomaly(
        source=e.source,
        kind="night_activity",
        zone=e.zone,
        reason=f"Activity in {_label(e.zone)} at {_hhmm(minute)} — unusual for this hour",
        detected_at=e.ts,
        details={"event_id": e.id, "slot": slot, "slot_days": r.hist[slot], "days": r.days_seen},
    )


def check_tick(routines: list[Routine], now: datetime, cfg: Config) -> list[Anomaly]:
    """late_start per zone + long_inactivity for ONE source's routines. O(zones)."""
    t = now.astimezone(ZoneInfo(cfg.tz))
    today, minute = t.date(), t.hour * 60 + t.minute
    out = [a for r in routines if (a := _late_start(r, now, today, minute, cfg))]
    if (a := _long_inactivity(routines, now, today, minute, cfg)) is not None:
        out.append(a)
    return out


def _late_start(r: Routine, now: datetime, today: date, minute: int, cfg: Config):
    if cfg.late_start_zones is not None and r.zone not in cfg.late_start_zones:
        return None
    if r.today == today and r.today_first is not None:
        return None
    if r.days_seen >= cfg.min_days_for_checks and r.median_first is not None:
        usual = r.median_first
        buffer = max(round(cfg.mad_multiplier * (r.mad_first or 0)), cfg.late_buffer_min_floor)
    elif r.zone in cfg.cold_start_zones:
        usual, buffer = _minutes(cfg.default_first_activity), cfg.late_buffer_min_floor
    else:
        return None
    if minute <= usual + buffer or not _claim(r, "late_start", today):
        return None
    return Anomaly(
        source=r.source,
        kind="late_start",
        zone=r.zone,
        reason=f"No {_label(r.zone)} activity by {_hhmm(minute)} (usually {_hhmm(usual)})",
        detected_at=now,
        details={"usual_first": usual, "threshold": usual + buffer, "days": r.days_seen},
    )


def _long_inactivity(routines: list[Routine], now: datetime, today: date, minute: int, cfg: Config):
    if not _active(minute, cfg):
        return None
    seen = [r for r in routines if r.last_event_ts is not None]
    if not seen:
        return None
    last = max(seen, key=lambda r: r.last_event_ts)  # type: ignore[arg-type, return-value]
    tz = ZoneInfo(cfg.tz)
    start = datetime.combine(today, datetime.min.time(), tz) + timedelta(
        minutes=_minutes(cfg.waking_start)
    )
    idle = now - max(last.last_event_ts, start)  # type: ignore[type-var]
    if idle <= timedelta(minutes=cfg.inactivity_minutes):
        return None
    if any(r.fired.get("long_inactivity") == today.isoformat() for r in routines):
        return None
    for r in routines:
        r.fired["long_inactivity"] = today.isoformat()
    idle_min = int(idle.total_seconds() // 60)
    lt = last.last_event_ts.astimezone(tz)  # type: ignore[union-attr]
    when = _hhmm(lt.hour * 60 + lt.minute)
    if lt.date() == today - timedelta(days=1):
        when += " yesterday"
    elif lt.date() != today:
        when += f" on {lt:%d %b}"
    return Anomaly(
        source=last.source,
        kind="long_inactivity",
        zone=None,
        reason=(
            f"No activity anywhere for {idle_min // 60} h {idle_min % 60} min "
            f"(last: {_label(last.zone)} at {when})"
        ),
        detected_at=now,
        details={"idle_minutes": idle_min, "last_zone": last.zone},
    )


def _claim(r: Routine, kind: str, day: date) -> bool:
    if r.fired.get(kind) == day.isoformat():
        return False
    r.fired[kind] = day.isoformat()
    return True


def _night_of(day: date, minute: int, cfg: Config) -> date:
    """The evening a night belongs to: 02:10 on the 23rd is the night of the 22nd."""
    return day if minute >= _minutes(cfg.waking_end) else day - timedelta(days=1)


def _claim_night(r: Routine, ts: datetime, night: date, cfg: Config) -> bool:
    """Allow up to `night_max_per_night` alerts per night, `night_repeat_minutes` apart. O(1)."""
    f = r.fired
    count = 0
    if f.get("night_activity") == night.isoformat():
        last = f.get("night_activity_last")  # missing on routines stored before this rule
        count = int(f.get("night_activity_count", "1"))
        too_soon = last is None or ts - datetime.fromisoformat(last) < timedelta(
            minutes=cfg.night_repeat_minutes
        )
        if too_soon or count >= cfg.night_max_per_night:
            return False
    f["night_activity"] = night.isoformat()
    f["night_activity_count"] = str(count + 1)
    f["night_activity_last"] = ts.isoformat()
    return True


def _active(minute: int, cfg: Config) -> bool:
    start, end = _minutes(cfg.waking_start), _minutes(cfg.waking_end)
    return start <= minute < end if start <= end else minute >= start or minute < end


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _label(zone: str) -> str:
    return zone.replace("_", " ")
