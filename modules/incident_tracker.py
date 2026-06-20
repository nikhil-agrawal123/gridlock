"""Incident tracker -- per-corridor state machine for the feedback loop.

State machine:
    NORMAL --[speed deviation > ONSET_DEVIATION]--> INCIDENT_OPEN
    INCIDENT_OPEN --[deviation < RESOLVE_DEVIATION OR 24h timeout]--> NORMAL
                                                                      (logs outcome)

State is persisted in ``data/feedback/corridor_state.json`` so restarts
resume tracking.  The scheduler calls ``process_corridor_tick()`` every
15 minutes per corridor.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from modules import feedback_logger as fb

logger = logging.getLogger("trafficsense.incident_tracker")

STATE_FILE = Path("data/feedback/corridor_state.json")

# Speed-deviation thresholds (fraction of free-flow lost)
ONSET_DEVIATION = 0.35       # 35% speed drop → incident
RESOLVE_DEVIATION = 0.10     # back within 10% → resolved
TIMEOUT_HOURS = 24


# ── persistence ─────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Corrupt corridor state file, starting fresh: %r", e)
    return {}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, default=str, indent=2))


# ── helpers ─────────────────────────────────────────────────────────
def _now():
    return datetime.now(timezone.utc)


def count_neighbours_congested(corridor: str, deviation_threshold=ONSET_DEVIATION) -> int:
    """Count how many OTHER corridors currently have an open incident.
    Used to populate actual_corridor_count on resolution."""
    state = load_state()
    return sum(
        1 for c, s in state.items()
        if c != corridor and s.get("status") == "INCIDENT_OPEN"
    )


# ── core: per-tick processing ───────────────────────────────────────
def process_corridor_tick(corridor: str, speed_now, freeflow_speed,
                          model_prediction: dict):
    """Called every 15 min per corridor from the scheduler poll loop.

    Parameters
    ----------
    corridor : str
        Corridor name / ID.
    speed_now : float or None
        Current speed from TomTom (km/h).  None if mock.
    freeflow_speed : float or None
        Free-flow speed from TomTom (km/h).  None if mock.
    model_prediction : dict
        Keys: impact_level, duration_min, corridor_count, score,
              features (dict), event_ctx, model_version.
    """
    state = load_state()
    cs = state.get(corridor, {"status": "NORMAL"})

    # Compute deviation; if TomTom data is unavailable fall back to the
    # composite score as a proxy (normalised to 0-1).
    if speed_now is not None and freeflow_speed and freeflow_speed > 0:
        deviation = max(0.0, 1.0 - (speed_now / freeflow_speed))
    else:
        deviation = model_prediction.get("score", 0) / 100.0

    now = _now()

    # ── NORMAL → INCIDENT_OPEN ──────────────────────────────────────
    if cs["status"] == "NORMAL" and deviation > ONSET_DEVIATION:
        incident_id = fb.log_prediction(
            corridor=corridor,
            features=model_prediction.get("features", {}),
            impact=model_prediction["impact_level"],
            duration=model_prediction["duration_min"],
            corridor_count=model_prediction.get("corridor_count", 1),
            score=model_prediction.get("score", 0),
            event_ctx=model_prediction.get("event_ctx"),
            model_version=model_prediction.get("model_version", "unknown"),
        )
        cs = {
            "status": "INCIDENT_OPEN",
            "incident_id": incident_id,
            "opened_at": now.isoformat(),
            "officer_present": model_prediction.get("officer_dispatched", False),
        }
        logger.info("INCIDENT_OPEN on %s  id=%s  deviation=%.2f",
                     corridor, incident_id, deviation)

    # ── INCIDENT_OPEN → RESOLVED ────────────────────────────────────
    elif cs["status"] == "INCIDENT_OPEN":
        opened_at = datetime.fromisoformat(cs["opened_at"])
        timed_out = (now - opened_at) > timedelta(hours=TIMEOUT_HOURS)

        if deviation < RESOLVE_DEVIATION or timed_out:
            method = "timeout_24h" if timed_out else "auto_speed_recovery"
            fb.log_outcome(
                incident_id=cs["incident_id"],
                predicted_at=opened_at,
                resolved_at=now,
                actual_corridor_count=count_neighbours_congested(corridor) + 1,
                resolution_method=method,
                officer_present=cs.get("officer_present", False),
            )
            fb.close_incident(corridor)
            logger.info("RESOLVED %s  id=%s  method=%s",
                         corridor, cs["incident_id"], method)
            cs = {"status": "NORMAL"}

    state[corridor] = cs
    save_state(state)


# ── force-open for planned events ───────────────────────────────────
def force_open(corridor: str, model_prediction: dict) -> str:
    """Opens an incident without waiting for speed deviation.

    Used when an officer activates Phase 2 for a planned event — the
    incident is pre-opened on all affected corridors and the normal
    poll loop handles resolution.

    Returns the incident_id.
    """
    state = load_state()
    cs = state.get(corridor, {"status": "NORMAL"})
    if cs["status"] == "INCIDENT_OPEN":
        return cs["incident_id"]  # already open

    now = _now()
    incident_id = fb.log_prediction(
        corridor=corridor,
        features=model_prediction.get("features", {}),
        impact=model_prediction["impact_level"],
        duration=model_prediction["duration_min"],
        corridor_count=model_prediction.get("corridor_count", 1),
        score=model_prediction.get("score", 0),
        event_ctx=model_prediction.get("event_ctx"),
        model_version=model_prediction.get("model_version", "unknown"),
    )
    state[corridor] = {
        "status": "INCIDENT_OPEN",
        "incident_id": incident_id,
        "opened_at": now.isoformat(),
        "officer_present": True,
    }
    save_state(state)
    logger.info("FORCE_OPEN (planned event) on %s  id=%s", corridor, incident_id)
    return incident_id


# ── queries ─────────────────────────────────────────────────────────
def get_active_incidents() -> list:
    """Return all corridors with status INCIDENT_OPEN."""
    state = load_state()
    now = _now()
    active = []
    for corridor, cs in state.items():
        if cs.get("status") == "INCIDENT_OPEN":
            opened_at = datetime.fromisoformat(cs["opened_at"])
            age_min = (now - opened_at).total_seconds() / 60
            active.append({
                "corridor": corridor,
                "incident_id": cs["incident_id"],
                "opened_at": cs["opened_at"],
                "age_minutes": round(age_min, 1),
                "officer_present": cs.get("officer_present", False),
            })
    return active


def manual_resolve(incident_id: str, actual_corridor_count: int = 1) -> dict:
    """Officer manually closes an incident from the dashboard.

    Returns {status, incident_id} on success or {error} if not found.
    """
    state = load_state()
    corridor = next(
        (c for c, s in state.items() if s.get("incident_id") == incident_id),
        None,
    )
    if not corridor:
        return {"error": "incident not found or already resolved"}

    cs = state[corridor]
    opened_at = datetime.fromisoformat(cs["opened_at"])
    now = _now()

    fb.log_outcome(
        incident_id=incident_id,
        predicted_at=opened_at,
        resolved_at=now,
        actual_corridor_count=actual_corridor_count,
        resolution_method="officer_manual_close",
        officer_present=cs.get("officer_present", False),
    )
    fb.close_incident(corridor)
    state[corridor] = {"status": "NORMAL"}
    save_state(state)
    logger.info("MANUAL_RESOLVE %s  id=%s", corridor, incident_id)
    return {"status": "resolved", "incident_id": incident_id}
