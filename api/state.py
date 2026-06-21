"""Shared in-memory state for the demo: which events are in their "Phase 2"
(live monitoring) window, used by both the event-activation endpoint and the
live-polling loop/corridor-risk endpoint to inject event context.

Both caches are bounded so a long-running backend doesn't grow without limit:
EVENT_BRIEFS evicts the oldest brief past a cap (each brief holds route
geometries, so they're not tiny), and expired ACTIVE_EVENTS are purged on read.
"""
from collections import OrderedDict
from datetime import datetime

MAX_BRIEFS = 25  # plenty for the demo; oldest evicted beyond this


class _BoundedBriefs(OrderedDict):
    """Insertion-ordered cache that drops the least-recently-set brief once it
    exceeds MAX_BRIEFS, so EVENT_BRIEFS can't grow unbounded."""

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        while len(self) > MAX_BRIEFS:
            self.popitem(last=False)


ACTIVE_EVENTS = {}  # event_id -> {corridors, multiplier, end_time, name}
EVENT_BRIEFS = _BoundedBriefs()  # event_id -> last generated /event-impact brief


def _purge_expired_events(now):
    """Drop active events whose monitoring window has closed."""
    for k in [k for k, ev in ACTIVE_EVENTS.items() if ev["end_time"] <= now]:
        del ACTIVE_EVENTS[k]


def compute_multiplier(attendance):
    """Bigger crowds push the congestion multiplier up, capped at 2.5x."""
    return 1.0 + min(1.5, attendance / 40000 * 0.5)


def get_event_context(corridor, at=None):
    """Event pressure on a corridor at time ``at`` (defaults to now). Passing a
    future ``at`` lets the forecast projection check whether an active event is
    still inside its window at the horizon being projected."""
    at = at or datetime.now()
    _purge_expired_events(datetime.now())
    for ev in ACTIVE_EVENTS.values():
        if corridor in ev["corridors"] and at < ev["end_time"]:
            return {
                "event_nearby": 1,
                "congestion_multiplier": ev["multiplier"],
                "corridors_under_pressure": len(ev["corridors"]),
            }
    return {"event_nearby": 0, "congestion_multiplier": 1.0, "corridors_under_pressure": 0}
