"""Feedback logger -- the data-collection half of the retraining loop.

Two linked snapshots per incident, append-only parquet partitioned by date:

  Snapshot A (prediction): logged when the pipeline forecasts an incident,
      before the outcome is known.  -> data/feedback/predictions/<date>.parquet
  Snapshot B (outcome): logged when the incident resolves (TomTom speed
      recovers, officer closes, or 24h timeout). -> data/feedback/outcomes/<date>.parquet

The two join on `incident_id`; together they give a feature row with a
ground-truth label that the next retrain learns from. No database -- just
files, same parquet format as clean_featured.parquet.
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from derive_targets import compute_impact_level

FEEDBACK_DIR = Path("data/feedback")
PREDICTIONS_DIR = FEEDBACK_DIR / "predictions"
OUTCOMES_DIR = FEEDBACK_DIR / "outcomes"

# In-memory map of corridors with an unresolved incident: corridor -> record.
# Rebuilt from disk on startup so restarts don't lose open incidents.
OPEN_INCIDENTS = {}


def _now():
    return datetime.now(timezone.utc)


def _append_parquet(directory: Path, record: dict, when: datetime):
    directory.mkdir(parents=True, exist_ok=True)
    f = directory / f"{when:%Y-%m-%d}.parquet"
    df_new = pd.DataFrame([record])
    if f.exists():
        df_new = pd.concat([pd.read_parquet(f), df_new], ignore_index=True)
    df_new.to_parquet(f, index=False)


def log_prediction(corridor, features, impact, duration, corridor_count,
                   score, event_ctx, model_version):
    """Snapshot A. `features` is the dict of model inputs at prediction time.
    Returns the incident_id and registers the corridor as having an open
    incident."""
    now = _now()
    incident_id = str(uuid.uuid4())
    record = {
        "incident_id": incident_id,
        "predicted_at": now.isoformat(),
        "corridor": corridor,
        "feature_snapshot": json.dumps(features, default=str),
        "predicted_impact_level": str(impact),
        "predicted_duration_min": int(duration),
        "predicted_corridor_count": int(corridor_count),
        "composite_score": float(score),
        "event_context": json.dumps(event_ctx) if event_ctx else None,
        "model_version": model_version,
    }
    _append_parquet(PREDICTIONS_DIR, record, now)
    OPEN_INCIDENTS[corridor] = {
        "incident_id": incident_id,
        "predicted_at": now,
        "corridor": corridor,
    }
    return incident_id


def log_outcome(incident_id, predicted_at, resolved_at, actual_corridor_count,
                resolution_method, officer_present=False):
    """Snapshot B. Derives actual_resolution_min + actual_impact_level (same
    duration-only binning as target derivation) and appends the outcome row."""
    if isinstance(predicted_at, str):
        predicted_at = datetime.fromisoformat(predicted_at)
    actual_min = max(0.0, (resolved_at - predicted_at).total_seconds() / 60)
    record = {
        "incident_id": incident_id,
        "resolved_at": resolved_at.isoformat(),
        "actual_resolution_min": round(actual_min, 1),
        "actual_impact_level": compute_impact_level(actual_min),
        "actual_corridor_count": int(actual_corridor_count),
        "resolution_method": resolution_method,
        "officer_present": bool(officer_present),
    }
    _append_parquet(OUTCOMES_DIR, record, resolved_at)


# --- open-incident helpers (used by the scheduler) -----------------------
def has_open_incident(corridor):
    return corridor in OPEN_INCIDENTS


def get_open_incident(corridor):
    return OPEN_INCIDENTS.get(corridor)


def close_incident(corridor):
    return OPEN_INCIDENTS.pop(corridor, None)


def iter_open_incidents():
    return list(OPEN_INCIDENTS.values())


def rebuild_open_incidents():
    """On startup, mark as open any predicted incident with no matching
    outcome yet, so a restart resumes tracking instead of losing them."""
    OPEN_INCIDENTS.clear()
    preds = _read_all(PREDICTIONS_DIR)
    if preds.empty:
        return
    outs = _read_all(OUTCOMES_DIR)
    resolved = set(outs["incident_id"]) if not outs.empty else set()
    preds = preds[~preds["incident_id"].isin(resolved)]
    # keep the latest open incident per corridor
    preds = preds.sort_values("predicted_at").drop_duplicates("corridor", keep="last")
    for _, r in preds.iterrows():
        OPEN_INCIDENTS[r["corridor"]] = {
            "incident_id": r["incident_id"],
            "predicted_at": datetime.fromisoformat(r["predicted_at"]),
            "corridor": r["corridor"],
        }


# --- counts (used by the Analytics page) ---------------------------------
def _read_all(directory: Path) -> pd.DataFrame:
    if not directory.exists():
        return pd.DataFrame()
    files = sorted(directory.glob("*.parquet"))
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def resolved_count() -> int:
    """Total resolved incidents (predictions that have a matching outcome)."""
    preds, outs = _read_all(PREDICTIONS_DIR), _read_all(OUTCOMES_DIR)
    if preds.empty or outs.empty:
        return 0
    return int(preds["incident_id"].isin(set(outs["incident_id"])).sum())
