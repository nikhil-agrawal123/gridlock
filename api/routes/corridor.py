""" /corridor-risk and /corridors/all: the unplanned,
always-on pipeline. Called every 15 min by the scheduler, and on-demand by
the Live Impact Map dashboard page.
"""
import math
from datetime import datetime, timedelta

from fastapi import APIRouter

from api.state import get_event_context
from modules import model_registry as mr
from modules.corridor_lookup import get_all_corridors, get_corridor_centroids
from modules.feature_builder import build_live_features, predict_label
from modules.fusion import compute_score, score_breakdown
from modules.tomtom_client import get_speeds
from modules.weather import get_weather_factor

router = APIRouter()

_LATEST_STATE = {}  # corridor -> last computed state, refreshed by the scheduler

# A live speed reading loses validity over time, so when we project a corridor
# forward we decay it toward the model's forecast with weight exp(-horizon/TAU).
# At +30 min ~51% of the reading survives, at +60 min ~26%, at +90 min ~14%.
NOWCAST_TAU_MIN = 45.0
_RISK_W = {"Low": 0.0, "Medium": 0.5, "High": 1.0}


def get_model_risk(corridor: str) -> float:
    """High/Medium/Low impact_level probability collapsed to a single risk in [0,1]."""
    clf = mr.get_impact_clf()
    feats = build_live_features(corridor)
    proba = clf.predict_proba(feats)[0]
    classes = list(clf.classes_)
    weights = {"Low": 0.0, "Medium": 0.5, "High": 1.0}
    return float(sum(p * weights.get(str(c), 0.5) for p, c in zip(proba, classes)))


def compute_corridor_state(corridor: str) -> dict:
    clf, reg_dur = mr.get_impact_clf(), mr.get_duration_reg()
    now = datetime.now()
    feats = build_live_features(corridor, now)
    impact = predict_label(clf, feats)
    duration = int(reg_dur.predict(feats)[0])

    lat, lon = get_corridor_centroids().get(corridor, (12.97, 77.59))
    # Pass the corridor's coordinates so the live TomTom Flow Segment Data
    # endpoint can be queried for the nearest road segment (falls back to
    # mock internally if no API key / the call fails).
    speed_data = get_speeds(corridor, float(lat), float(lon))
    model_risk = get_model_risk(corridor)
    event_ctx = get_event_context(corridor)
    wx = get_weather_factor(float(lat), float(lon))
    event_mult = event_ctx["congestion_multiplier"]
    score = compute_score(
        speed_data["deviation"], model_risk,
        event_mult=event_mult, weather=wx["factor"], hour=now.hour,
    )
    breakdown = score_breakdown(speed_data["deviation"], model_risk, event_mult, wx["factor"])

    state = {
        "corridor": corridor,
        "lat": float(lat),
        "lon": float(lon),
        "impact_level": impact,
        "congestion_duration_min": duration,
        "composite_score": score,
        "score_breakdown": breakdown["components"],
        "tomtom_deviation": speed_data["deviation"],
        "tomtom_current_speed": speed_data["current_speed"],
        "tomtom_free_flow_speed": speed_data["free_flow_speed"],
        "tomtom_road_closure": speed_data["road_closure"],
        "tomtom_is_mock": speed_data["is_mock"],
        "weather_factor": wx["factor"],
        "weather_condition": wx["condition"],
        "weather_is_mock": wx["is_mock"],
        "event_nearby": bool(event_ctx["event_nearby"]),
        "updated_at": now.isoformat(),
    }
    _LATEST_STATE[corridor] = state
    return state


def project_state(state: dict, horizon_min: int) -> dict:
    """Project a live corridor state forward by ``horizon_min`` minutes.

    The model component is re-predicted at the future clock (CatBoost knows the
    daily rhythm); the live TomTom reading is decayed toward that forecast with
    a persistence weight exp(-horizon/TAU) -- the further out we look, the more
    the learned pattern leads the stale observation. The event window is
    re-checked at the horizon and weather is held (no future forecast).
    ``horizon_min<=0`` returns the live state untouched."""
    if horizon_min <= 0:
        return {**state, "is_forecast": False, "horizon_min": 0}

    corridor = state["corridor"]
    future = datetime.now() + timedelta(minutes=horizon_min)
    clf, reg_dur = mr.get_impact_clf(), mr.get_duration_reg()
    feats = build_live_features(corridor, future)

    impact = predict_label(clf, feats)
    duration = int(reg_dur.predict(feats)[0])
    proba = clf.predict_proba(feats)[0]
    classes = list(clf.classes_)
    model_risk = float(sum(p * _RISK_W.get(str(c), 0.5) for p, c in zip(proba, classes)))

    persistence = math.exp(-horizon_min / NOWCAST_TAU_MIN)
    obs_dev = state.get("tomtom_deviation") or 0.0
    proj_dev = max(0.0, min(1.0, persistence * obs_dev + (1 - persistence) * model_risk))

    event_ctx = get_event_context(corridor, at=future)
    event_mult = event_ctx["congestion_multiplier"]
    weather = state.get("weather_factor", 1.0)

    score = compute_score(proj_dev, model_risk, event_mult=event_mult,
                          weather=weather, hour=future.hour)
    breakdown = score_breakdown(proj_dev, model_risk, event_mult, weather)

    return {
        **state,
        "impact_level": impact,
        "congestion_duration_min": duration,
        "composite_score": score,
        "score_breakdown": breakdown["components"],
        # Projected (blended) congestion; live speeds are nulled so the UI shows
        # the blended slowdown rather than a stale "now" speed pair.
        "tomtom_deviation": round(proj_dev, 3),
        "tomtom_current_speed": None,
        "tomtom_free_flow_speed": None,
        "event_nearby": bool(event_ctx["event_nearby"]),
        "is_forecast": True,
        "horizon_min": horizon_min,
        "forecast_for": future.isoformat(),
        "forecast_hour": future.hour,
        "live_persistence": round(persistence, 2),
        "observed_deviation": round(obs_dev, 3),
        "model_risk": round(model_risk, 3),
    }


@router.get("/corridor-risk/{corridor}")
def corridor_risk(corridor: str):
    return compute_corridor_state(corridor)


@router.get("/corridors/all")
def corridors_all():
    for corridor in get_all_corridors():
        if corridor not in _LATEST_STATE:
            compute_corridor_state(corridor)
    return [_LATEST_STATE[c] for c in get_all_corridors()]


@router.get("/corridors/projected")
def corridors_projected(horizon_min: int = 30):
    """Same shape as /corridors/all, but every corridor projected ``horizon_min``
    minutes ahead. Reuses the cached live reading as the anchor (no new TomTom
    calls), so it's fast and consistent with the live map."""
    horizon_min = max(0, min(180, horizon_min))
    for corridor in get_all_corridors():
        if corridor not in _LATEST_STATE:
            compute_corridor_state(corridor)
    return [project_state(_LATEST_STATE[c], horizon_min) for c in get_all_corridors()]
