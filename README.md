# routine-guard

Learn the daily rhythm of any timestamped event stream, then flag the days that break it,
with one plain sentence explaining why.

Smart-home motion sensors, elder care, a server's request log, a shop's door counter:
if "when things usually happen" matters, routine-guard learns it from about two weeks of
events and tells you when today looks wrong. Pure Python, standard library only, typed,
deterministic, no ML.

## The three rules

| Rule | Fires when | Cost |
|---|---|---|
| **late_start** | a zone has no activity today by its usual first time + max(3 × MAD, 30 min) | O(zones) per tick |
| **long_inactivity** | nothing anywhere for 4 h during active hours (night counted from the start of active hours) | O(zones) per tick |
| **night_activity** | activity outside active hours in a 15-min slot used on < 5% of learned days; again ≥ 30 min after the last one, max 3 a night | O(1) per event |

Learning is O(1) per event; closing a day is O(D log D) with D = 14. late_start fires at most
once per local day per zone, long_inactivity once per day per source, and night_activity up to
`night_max_per_night` (3) times a night, `night_repeat_minutes` (30) apart. Every threshold is in `Config`, including which zones can be "late" (`late_start_zones`; Saathi uses kitchen and bedroom).

## Install

```
pip install git+https://github.com/krishnadityasingh18-create/routine-guard
```

## Usage

```python
from datetime import UTC, datetime, timedelta
from routine_guard import Config, Event, check_event, check_tick, learn, update

cfg = Config(tz="Asia/Kolkata", night_zones=frozenset({"front_door"}))
start = datetime(2026, 10, 1, 2, 30, tzinfo=UTC)  # 08:00 in Kolkata
history = [Event(f"e{d}", "home-1", "kitchen", start + timedelta(days=d)) for d in range(14)]
history += [
    Event(f"d{d}", "home-1", "front_door", start + timedelta(days=d, hours=9)) for d in range(14)
]
routines = learn(history, cfg)  # {(source, zone): Routine}

now = datetime(2026, 10, 15, 5, 0, tzinfo=UTC)  # 10:30 local, no kitchen activity yet today
for a in check_tick(list(routines.values()), now, cfg):
    print(a.kind, "-", a.reason)
# late_start - No kitchen activity by 10:30 (usually 08:00)
# long_inactivity - No activity anywhere for 4 h 30 min (last: front door at 17:00 yesterday)

door = Event("x", "home-1", "front_door", datetime(2026, 10, 15, 20, 40, tzinfo=UTC))  # 02:10
print(check_event(routines[("home-1", "front_door")], door, cfg).reason)
# Activity in front door at 02:10 — unusual for this hour
update(routines[("home-1", "front_door")], door, cfg)  # then keep learning
```

`to_dict` / `from_dict` turn a `Routine` into JSON-safe ints, lists and strings, so it can
live in any key-value store (DynamoDB, Redis, a file). Routines are updated in place, and
`check_*` record what fired today, so save a routine after updating or checking it.

## Why

Built for [Saathi](https://github.com/mayank-ydvv/saathi), an elder-care guardian on Ring for
the Amazon Developer Hackathon 2026. Many parents live alone while their children work in
other cities. Saathi learns a parent's normal day from Ring motion and doorbell events and
makes sure someone checks in when the day isn't normal. The engine has nothing Ring-specific
in it, so we released it on its own.

## Development

```
pip install -e ".[dev]"
pytest -q && ruff check . && ruff format --check .
```

MIT licensed.
