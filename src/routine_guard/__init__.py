"""routine-guard: learn a daily rhythm from timestamped events and flag days that break it."""

from routine_guard.anomaly import check_event, check_tick
from routine_guard.models import Anomaly, Config, Event, Routine
from routine_guard.routine import from_dict, learn, new_routine, rollover, to_dict, update
from routine_guard.trends import weekly_trend

__version__ = "0.1.0"
__all__ = [
    "Anomaly",
    "Config",
    "Event",
    "Routine",
    "check_event",
    "check_tick",
    "from_dict",
    "learn",
    "new_routine",
    "rollover",
    "to_dict",
    "update",
    "weekly_trend",
]
