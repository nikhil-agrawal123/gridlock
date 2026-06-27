"""Incident management endpoints:
  GET  /incidents/active                  list open incidents
  POST /incident/{incident_id}/resolve    officer manual close
  POST /incident/report                   officer manual incident report (feedback)
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from modules import incident_tracker as tracker
from datetime import datetime
import logging

router = APIRouter()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trafficsense.incident")


@router.get("/incidents/active")
def active_incidents():
    """Return all corridors with an open incident."""
    logger.info("Active incidents requested at %s", datetime.now().isoformat())
    return tracker.get_active_incidents()


@router.post("/incident/{incident_id}/resolve")
def resolve_incident(incident_id: str, actual_corridor_count: int = 1):
    """Officer manually closes an incident from the dashboard.

    Logs the outcome (Snapshot B) with resolution_method='officer_manual_close'
    and resets the corridor to NORMAL.
    """
    logger.info("Manual incident resolution requested for %s at %s", incident_id, datetime.now().isoformat())
    result = tracker.manual_resolve(incident_id, actual_corridor_count)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


class IncidentReport(BaseModel):
    """An officer's first-hand account of a resolved incident: what went wrong
    and where. Becomes a labelled training example for the next retrain."""
    corridor: str                                       # where
    cause: str = "general_breakdown"                    # what went wrong (reason_breakdown_clean)
    veh_type: str = "unknown"                           # vehicle involved
    cause_severity: int = Field(3, ge=1, le=5)          # officer severity rating
    road_closure: bool = False
    is_planned: bool = False
    duration_min: float = Field(..., gt=0, le=1440)     # how long it took to clear
    corridors_affected: int = Field(1, ge=1, le=20)     # how many corridors backed up
    started_at: Optional[datetime] = None               # when it began (default: duration_min ago)
    notes: str = ""


@router.post("/incident/report")
def report_incident(report: IncidentReport):
    """Officer-submitted ground truth for an incident the automatic tracker
    never caught. Builds the corridor's feature context at the incident time,
    overrides it with the officer's first-hand cause details, records what the
    current model *would* have predicted (for comparison), and writes a linked
    prediction+outcome pair the next retrain learns from.
    """
    logger.info("Manual incident report submitted for %s at %s", report.corridor, datetime.now().isoformat())
    from modules import feedback_logger as fb
    from modules.corridor_lookup import get_all_corridors
    from modules.feature_builder import build_live_features
    from train_model import CAT_FEATURES, FEATURES

    if report.corridor not in get_all_corridors():
        raise HTTPException(status_code=422,
                            detail=f"unknown corridor '{report.corridor}'")

    # When it happened: use the officer's start time (naive local, matching the
    # tracker's feature timestamps) or default to duration_min ago.
    started = report.started_at
    if started is not None and started.tzinfo is not None:
        started = started.replace(tzinfo=None)
    if started is None:
        started = datetime.now() - timedelta(minutes=report.duration_min)
    resolved = started + timedelta(minutes=report.duration_min)

    # Feature snapshot: the corridor's structural baseline at that time of day,
    # overridden with the officer's first-hand cause details.
    feats = build_live_features(report.corridor, started).iloc[0].to_dict()
    feats.update({
        "cause_severity": int(report.cause_severity),
        "road_closure": int(report.road_closure),
        "is_planned": int(report.is_planned),
        "veh_type": str(report.veh_type),
        "reason_breakdown_clean": str(report.cause),
    })
    if report.notes:
        feats["description_length"] = float(len(report.notes))

    # What the current production model would have called it -- recorded for
    # comparison, never used as a label. Skipped gracefully if models can't load.
    predicted = None
    try:
        import pandas as pd

        from modules import model_registry as mr

        X = pd.DataFrame([feats])[FEATURES]
        for c in CAT_FEATURES:
            X[c] = X[c].astype(str)
        predicted = {
            "impact_level": str(mr.get_impact_clf().predict(X, thread_count=mr.PREDICT_THREADS)[0][0]),
            "duration_min": round(float(mr.get_duration_reg().predict(X, thread_count=mr.PREDICT_THREADS)[0]), 1),
            "corridor_count": int(round(mr.get_corridor_reg().predict(X, thread_count=mr.PREDICT_THREADS)[0])),
            "model_version": mr.current_version(),
        }
    except Exception:
        predicted = None

    logger.info("Logging manual incident report for %s at %s", report.corridor, datetime.now().isoformat())
    incident_id = fb.log_manual_report(
        corridor=report.corridor,
        features=feats,
        started_at=started,
        resolved_at=resolved,
        actual_corridor_count=report.corridors_affected,
        predicted=predicted,
        notes=report.notes,
    )

    from derive_targets import compute_impact_level
    return {
        "status": "logged",
        "incident_id": incident_id,
        "corridor": report.corridor,
        "actual_impact_level": compute_impact_level(report.duration_min),
        "actual_resolution_min": round(report.duration_min, 1),
        "predicted": predicted,
        "resolved_incidents": fb.resolved_count(),
    }
