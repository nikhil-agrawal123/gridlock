"""APScheduler runs inside the
FastAPI process, polling every corridor's TomTom deviation + model risk
every 15 minutes and flagging any corridor whose composite score crosses
the alert threshold.
"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from modules.corridor_lookup import get_all_corridors

logger = logging.getLogger("trafficsense.scheduler")
ALERT_THRESHOLD = 70

scheduler = BackgroundScheduler()


def poll_corridors():
    """Core unplanned pipeline -- refreshes every corridor's live state."""
    from api.routes.corridor import compute_corridor_state

    for corridor in get_all_corridors():
        state = compute_corridor_state(corridor)
        if state["composite_score"] > ALERT_THRESHOLD:
            logger.warning(
                "ALERT: %s composite_score=%.1f impact=%s",
                corridor, state["composite_score"], state["impact_level"],
            )


def start():
    if not scheduler.running:
        scheduler.add_job(poll_corridors, "interval", minutes=15, id="poll_corridors")
        scheduler.start()
