from datetime import UTC, date, datetime, timedelta

from routine_guard import (
    Config,
    Event,
    check_event,
    check_tick,
    from_dict,
    learn,
    new_routine,
    rollover,
    to_dict,
    update,
    weekly_trend,
)
from routine_guard.routine import HISTORY_DAYS

TODAY = date(2026, 10, 22)
CFG = Config(tz="UTC")


def at(hhmm: str, day: date = TODAY) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=UTC)


def ev(zone: str, hhmm: str, day: date = TODAY, type_: str = "activity") -> Event:
    return Event(f"{zone}-{day}-{hhmm}", "home", zone, at(hhmm, day), type_)


def learned(zone: str, first: str = "08:00", days: int = 14, extra=()):
    r = new_routine("home", zone)
    for d in range(days, 0, -1):
        for t in (first, "13:00", "21:00", *extra):
            update(r, ev(zone, t, TODAY - timedelta(days=d)), CFG)
    return rollover(r, TODAY)


# learning ---------------------------------------------------------------------------
def test_median_mad_and_slot_counts_once_per_day():
    r = new_routine("home", "kitchen")
    for d, t in enumerate(["08:00", "08:10", "07:50", "08:20", "08:00"]):
        update(r, ev("kitchen", t, TODAY + timedelta(days=d)), CFG)
        update(r, ev("kitchen", t, TODAY + timedelta(days=d)), CFG)  # duplicate
    rollover(r, TODAY + timedelta(days=5))
    assert (r.days_seen, r.median_first, r.mad_first) == (5, 480, 10)
    assert (r.hist[31], r.hist[32], r.hist[33]) == (1, 3, 1)


def test_window_evicts_oldest_day():
    r = new_routine("home", "kitchen")
    update(r, ev("kitchen", "03:00", TODAY), CFG)
    for d in range(1, 16):
        update(r, ev("kitchen", "08:00", TODAY + timedelta(days=d)), CFG)
    rollover(r, TODAY + timedelta(days=16))
    assert r.days_seen == HISTORY_DAYS and r.hist[12] == 0 and r.hist[32] == HISTORY_DAYS


def test_late_events_for_closed_day_ignored_and_types_filtered():
    cfg = Config(tz="UTC", activity_types=frozenset({"motion"}))
    r = new_routine("home", "kitchen")
    update(r, ev("kitchen", "09:00", type_="motion"), cfg)
    update(r, ev("kitchen", "07:00", type_="package"), cfg)
    update(r, ev("kitchen", "08:00", TODAY + timedelta(days=1), "motion"), cfg)
    update(r, ev("kitchen", "22:00", TODAY, "motion"), cfg)
    assert r.first_times == [540] and r.hist[88] == 0


def test_timezone_parameter_moves_the_day_boundary():
    r = new_routine("home", "kitchen")
    update(r, ev("kitchen", "20:00"), Config(tz="Asia/Kolkata"))  # 01:30 next day in IST
    assert r.today == TODAY + timedelta(days=1) and r.today_first == 90


def test_round_trip_and_learn():
    events = [ev("kitchen", "08:00", TODAY - timedelta(days=d)) for d in range(3)]
    events += [ev("door", "07:00", TODAY - timedelta(days=d)) for d in range(3)]
    routines = learn(reversed(events), CFG)
    assert sorted(routines) == [("home", "door"), ("home", "kitchen")]
    for r in routines.values():
        assert from_dict(to_dict(r)) == r


# rules ------------------------------------------------------------------------------
def test_late_start_once_per_day():
    r = learned("kitchen")
    assert check_tick([r], at("08:30"), CFG) == []
    [a] = [x for x in check_tick([r], at("10:15"), CFG) if x.kind == "late_start"]
    assert a.reason == "No kitchen activity by 10:15 (usually 08:00)"
    assert [x for x in check_tick([r], at("10:20"), CFG) if x.kind == "late_start"] == []


def test_cold_start_only_for_configured_zones():
    cfg = Config(tz="UTC", cold_start_zones=frozenset({"kitchen"}))
    k, b = new_routine("home", "kitchen"), new_routine("home", "bedroom")
    assert [(a.kind, a.zone) for a in check_tick([k, b], at("08:31"), cfg)] == [
        ("late_start", "kitchen")
    ]
    assert check_tick([new_routine("home", "kitchen")], at("08:31"), CFG) == []


def test_long_inactivity_in_active_hours_only():
    r = learned("living_room", first="07:00")
    update(r, ev("living_room", "13:05"), CFG)
    assert check_tick([r], at("17:05"), CFG) == []
    [a] = check_tick([r], at("17:15"), CFG)
    assert a.reason == "No activity anywhere for 4 h 10 min (last: living room at 13:05)"
    assert check_tick([r], at("18:00"), CFG) == []
    r2 = learned("living_room", first="07:00")
    update(r2, ev("living_room", "17:00"), CFG)
    assert check_tick([r2], at("23:30"), CFG) == []


def test_night_activity_rare_slot_once_and_zone_filter():
    r = learned("front_door", first="06:30")
    a = check_event(r, ev("front_door", "02:10"), CFG)
    assert a and a.reason == "Activity in front door at 02:10 — unusual for this hour"
    assert check_event(r, ev("front_door", "02:15"), CFG) is None
    assert check_event(learned("kitchen", extra=("23:00",)), ev("kitchen", "23:05"), CFG) is None
    only_door = Config(tz="UTC", night_zones=frozenset({"front_door"}))
    assert check_event(learned("bedroom"), ev("bedroom", "02:10"), only_door) is None


def test_weekly_trend():
    r = new_routine("home", "bedroom")
    r.first_times = [420] * 7 + [460] * 7
    assert weekly_trend(r) == "Waking about 40 minutes later this week"
    r.first_times = [420] * 7 + [440] * 7
    assert weekly_trend(r) is None


def test_readme_example_runs():
    import re
    from pathlib import Path

    readme = Path(__file__).parents[1].joinpath("README.md").read_text(encoding="utf-8")
    code = re.search(r"```python\n(.*?)```", readme, re.DOTALL).group(1)
    exec(compile(code, "README.md", "exec"), {})


def test_late_start_zones_limits_which_zones_can_be_late():
    cfg = Config(tz="UTC", late_start_zones=frozenset({"kitchen"}))
    door = learned("front_door", first="06:30")
    assert [a for a in check_tick([door], at("12:00"), cfg) if a.kind == "late_start"] == []
    assert [a.kind for a in check_tick([learned("kitchen")], at("12:00"), cfg)][0] == "late_start"


def test_night_alert_repeats_after_30_min_at_most_3_per_night():
    r = learned("front_door", first="06:30")
    nxt = TODAY + timedelta(days=1)
    times = [("23:30", TODAY), ("23:40", TODAY), ("00:10", nxt), ("02:10", nxt), ("02:30", nxt)]
    times += [("03:00", nxt)]
    fired = [t for t, d in times if check_event(r, ev("front_door", t, d), CFG)]
    assert fired == ["23:30", "00:10", "02:10"]
    assert check_event(r, ev("front_door", "02:10", TODAY + timedelta(days=2)), CFG)
    r2 = from_dict(to_dict(learned("front_door", first="06:30")))
    cfg = Config(tz="UTC", night_repeat_minutes=60, night_max_per_night=1)
    assert check_event(r2, ev("front_door", "01:00"), cfg)
    assert check_event(from_dict(to_dict(r2)), ev("front_door", "03:00"), cfg) is None
