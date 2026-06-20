"""Admin / model-ops endpoints for the retraining loop:
  POST /retrain            run the feedback merge + candidate train + validate
  GET  /model-info         current version, metrics, version history, pending
  POST /rollback/{version} revert current to an archived version
"""
from fastapi import APIRouter

from modules import feedback_logger as fb
from modules import model_registry as mr

router = APIRouter()


@router.post("/retrain")
def retrain():
    from retrain import run_retrain

    return run_retrain()


@router.get("/model-info")
def model_info():
    reg = mr.read_registry()
    return {
        "current": reg.get("current"),
        "metrics": mr.current_metrics(),
        "versions": reg.get("versions", []),
        "resolved_incidents": fb.resolved_count(),
        "feedback_used_at_last_retrain": reg.get("feedback_used", 0),
    }


@router.post("/rollback/{version_id}")
def rollback(version_id: str):
    ok = mr.rollback_to(version_id)
    return {"status": "rolled_back" if ok else "error",
            "current": mr.current_version()} if ok else {"status": "error",
            "detail": f"unknown version {version_id}"}
