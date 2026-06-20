"""Incident management endpoints:
  GET  /incidents/active            list open incidents
  POST /incident/{incident_id}/resolve   officer manual close
"""
from fastapi import APIRouter

from modules import incident_tracker as tracker

router = APIRouter()


@router.get("/incidents/active")
def active_incidents():
    """Return all corridors with an open incident."""
    return tracker.get_active_incidents()


@router.post("/incident/{incident_id}/resolve")
def resolve_incident(incident_id: str, actual_corridor_count: int = 1):
    """Officer manually closes an incident from the dashboard.

    Logs the outcome (Snapshot B) with resolution_method='officer_manual_close'
    and resets the corridor to NORMAL.
    """
    result = tracker.manual_resolve(incident_id, actual_corridor_count)
    if "error" in result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=result["error"])
    return result
