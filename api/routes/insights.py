"""Insight endpoints powering the explainability, KPI and timeline features:

  GET /explain/corridor/{corridor}  per-prediction SHAP attribution + the
                                    composite-score breakdown for one corridor
  GET /kpis/system                  cumulative time/fuel/money/CO2 saved to date
  GET /timeline/corridors           24-hour model-forecast risk series per
                                    corridor, for the playback scrubber
"""
from datetime import datetime

import pandas as pd
from fastapi import APIRouter

from modules import explainer, kpi
from modules import model_registry as mr
from modules.corridor_lookup import get_all_corridors, get_corridor_centroids
from modules.feature_builder import build_live_features

router = APIRouter()

_RISK_W = {"Low": 0.0, "Medium": 0.5, "High": 1.0}


@router.get("/explain/corridor/{corridor}")
def explain_corridor(corridor: str):
    """Why the model forecasts this corridor's impact level the way it does."""
    from api.routes.corridor import compute_corridor_state

    feats = build_live_features(corridor)
    explanation = explainer.explain_impact(feats)
    state = compute_corridor_state(corridor)
    return {
        "corridor": corridor,
        "model_version": mr.current_version(),
        "composite_score": state["composite_score"],
        "score_breakdown": state.get("score_breakdown", []),
        **explanation,
    }


@router.get("/kpis/system")
def kpis_system():
    return kpi.system_kpis()


@router.get("/timeline/corridors")
def timeline_corridors(hours: int = 24):
    """Model-only 24-hour forecast for every corridor (no live TomTom calls,
    so it's fast and deterministic). For each hour we re-derive the corridor's
    feature row with that hour set, then batch-predict impact level, duration
    and a 0-100 model-risk score in one shot."""
    hours = max(1, min(48, hours))
    corridors = get_all_corridors()
    centroids = get_corridor_centroids()
    today = datetime.now().replace(minute=0, second=0, microsecond=0)

    # Build one big feature frame: (corridor x hour) rows, predict once.
    rows, index = [], []
    for c in corridors:
        for h in range(hours):
            rows.append(build_live_features(c, today.replace(hour=h % 24)))
            index.append((c, h))
    X = pd.concat(rows, ignore_index=True)

    clf, reg = mr.get_impact_clf(), mr.get_duration_reg()
    classes = [str(cl) for cl in clf.classes_]
    proba = clf.predict_proba(X)
    durations = reg.predict(X)
    labels = clf.predict(X).flatten()

    series = {c: [] for c in corridors}
    for i, (c, h) in enumerate(index):
        risk = float(sum(p * _RISK_W.get(cl, 0.5) for p, cl in zip(proba[i], classes)))
        series[c].append({
            "hour": h,
            "impact_level": str(labels[i]),
            "score": round(risk * 100, 1),
            "congestion_duration_min": int(durations[i]),
        })

    out = []
    for c in corridors:
        lat, lon = centroids.get(c, (12.97, 77.59))
        peak = max(series[c], key=lambda s: s["score"])
        out.append({
            "corridor": c, "lat": float(lat), "lon": float(lon),
            "series": series[c], "peak_hour": peak["hour"], "peak_score": peak["score"],
        })
    return {"hours": hours, "generated_at": today.isoformat(), "corridors": out}
