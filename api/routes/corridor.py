""" /corridor-risk and /corridors/all: the unplanned,
always-on pipeline. Called every 15 min by the scheduler, and on-demand by
the Live Impact Map dashboard page.
"""
from datetime import datetime

import joblib
from fastapi import APIRouter

from api.state import get_event_context
from modules.corridor_lookup import get_all_corridors, get_corridor_centroids
from modules.feature_builder import build_live_features, predict_label
from modules.fusion import compute_score
from modules.tomtom_client import get_speeds

router = APIRouter()

clf = joblib.load("models/trained/impact_clf.pkl")
reg_dur = joblib.load("models/trained/duration_reg.pkl")

_LATEST_STATE = {}  # corridor -> last computed state, refreshed by the scheduler


def get_model_risk(corridor: str) -> float:
    """High/Medium/Low impact_level probability collapsed to a single risk in [0,1]."""
    feats = build_live_features(corridor)
    proba = clf.predict_proba(feats)[0]
    classes = list(clf.classes_)
    weights = {"Low": 0.0, "Medium": 0.5, "High": 1.0}
    return float(sum(p * weights.get(str(c), 0.5) for p, c in zip(proba, classes)))


def compute_corridor_state(corridor: str) -> dict:
    now = datetime.now()
    feats = build_live_features(corridor, now)
    impact = predict_label(clf, feats)
    duration = int(reg_dur.predict(feats)[0])

    speed_data = get_speeds(corridor)
    model_risk = get_model_risk(corridor)
    event_ctx = get_event_context(corridor)
    score = compute_score(
        speed_data["deviation"], model_risk,
        event_mult=event_ctx["congestion_multiplier"], hour=now.hour,
    )

    lat, lon = get_corridor_centroids().get(corridor, (12.97, 77.59))
    state = {
        "corridor": corridor,
        "lat": float(lat),
        "lon": float(lon),
        "impact_level": impact,
        "congestion_duration_min": duration,
        "composite_score": score,
        "tomtom_deviation": speed_data["deviation"],
        "tomtom_is_mock": speed_data["is_mock"],
        "event_nearby": bool(event_ctx["event_nearby"]),
        "updated_at": now.isoformat(),
    }
    _LATEST_STATE[corridor] = state
    return state


@router.get("/corridor-risk/{corridor}")
def corridor_risk(corridor: str):
    return compute_corridor_state(corridor)


@router.get("/corridors/all")
def corridors_all():
    for corridor in get_all_corridors():
        if corridor not in _LATEST_STATE:
            compute_corridor_state(corridor)
    return [_LATEST_STATE[c] for c in get_all_corridors()]
