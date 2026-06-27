"""APScheduler runs inside the FastAPI process. Every 15 minutes it polls
each corridor's live state and drives the incident-tracker state machine:

  - process_corridor_tick() handles onset / resolution / timeout
    transitions and writes prediction + outcome snapshots.

It also flags corridors crossing the alert threshold.
"""
import logging
from datetime import timedelta

import numpy as np
from apscheduler.schedulers.background import BackgroundScheduler

from modules import feedback_logger as fb
from modules import incident_tracker as tracker
from modules import model_registry as mr
from modules.corridor_lookup import get_all_corridors
from modules.feature_builder import build_live_features

logger = logging.getLogger("trafficsense.scheduler")

ALERT_THRESHOLD = 70

scheduler = BackgroundScheduler()


def _native(v):
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    return v


def _feature_dict(corridor):
    row = build_live_features(corridor).iloc[0].to_dict()
    return {k: _native(v) for k, v in row.items()}


def poll_corridors():
    from api.routes.corridor import compute_corridor_state

    states = [compute_corridor_state(c) for c in get_all_corridors()]
    for state in states:
        corridor = state["corridor"]
        try:
            # Build model_prediction dict for the incident tracker
            try:
                ccount = int(round(
                    mr.get_corridor_reg().predict(
                        build_live_features(corridor),
                        thread_count=mr.PREDICT_THREADS,
                    )[0]
                ))
            except Exception:
                ccount = 1

            from api.state import get_event_context
            event_ctx = get_event_context(corridor)

            prediction = {
                "impact_level": state["impact_level"],
                "duration_min": state["congestion_duration_min"],
                "corridor_count": ccount,
                "score": state["composite_score"],
                "features": _feature_dict(corridor),
                "event_ctx": event_ctx if event_ctx.get("event_nearby") else None,
                "model_version": mr.current_version(),
            }

            # Drive the state machine
            tracker.process_corridor_tick(
                corridor,
                speed_now=state.get("tomtom_current_speed"),
                freeflow_speed=state.get("tomtom_free_flow_speed"),
                model_prediction=prediction,
            )
        except Exception as e:  # feedback must never break the poll
            logger.warning("incident tracker failed for %s: %r", corridor, e)

        if state["composite_score"] > ALERT_THRESHOLD:
            logger.warning("ALERT %s score=%.1f impact=%s",
                           corridor, state["composite_score"], state["impact_level"])


def start():
    fb.rebuild_open_incidents()
    if not scheduler.running:
        scheduler.add_job(poll_corridors, "interval", minutes=15, id="poll_corridors")
        scheduler.start()
