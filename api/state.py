"""Shared in-memory state for the demo: which events are in their "Phase 2"
(live monitoring) window, used by both the event-activation endpoint and the
live-polling loop/corridor-risk endpoint to inject event context.

"""
from datetime import datetime

ACTIVE_EVENTS = {}  # event_id -> {corridors, multiplier, end_time, name}
EVENT_BRIEFS = {}  # event_id -> last generated /event-impact brief


def compute_multiplier(attendance):
    """Bigger crowds push the congestion multiplier up, capped at 2.5x."""
    return 1.0 + min(1.5, attendance / 40000 * 0.5)


def get_event_context(corridor, at=None):
    """Event pressure on a corridor at time ``at`` (defaults to now). Passing a
    future ``at`` lets the forecast projection check whether an active event is
    still inside its window at the horizon being projected."""
    at = at or datetime.now()
    for ev in ACTIVE_EVENTS.values():
        if corridor in ev["corridors"] and at < ev["end_time"]:
            return {
                "event_nearby": 1,
                "congestion_multiplier": ev["multiplier"],
                "corridors_under_pressure": len(ev["corridors"]),
            }
    return {"event_nearby": 0, "congestion_multiplier": 1.0, "corridors_under_pressure": 0}
