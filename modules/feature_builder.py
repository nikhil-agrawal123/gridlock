"""Builds CatBoost-ready feature rows for the two demo pipelines:
  - planned events (Event Planner page): hypothetical event injected onto a corridor
  - live/unplanned polling (Live Impact Map): "what does this corridor look like right now"
Both reuse each corridor's historical averages (from featured_v2.parquet) for
the columns that aren't event/time specific.
"""
from datetime import datetime
from functools import lru_cache

import pandas as pd

from train_model import FEATURES

FEATURED_PATH = "data/processed/featured_v2.parquet"

CAUSE_SEVERITY_BY_EVENT = {"rally": 4, "festival": 4, "sports": 3, "construction": 3}


@lru_cache(maxsize=1)
def get_corridor_stats():
    df = pd.read_parquet(FEATURED_PATH)
    mode_or = lambda default: (lambda s: s.mode().iat[0] if not s.mode().empty else default)

    def dominant(default, ignore):
        """Most common *informative* value for a corridor, ignoring placeholder /
        noise categories ('unknown', 'none', -1) so the corridor is described by
        its real dominant vehicle type / breakdown cause / blackspot cluster
        rather than the missing-data mode. Falls back to the overall mode, then
        the default, only when the corridor has no informative value at all."""
        ignore = set(ignore)

        def agg(s):
            informative = s[~s.isin(ignore)]
            m = informative.mode()
            if not m.empty:
                return m.iat[0]
            m = s.mode()
            return m.iat[0] if not m.empty else default

        return agg

    agg = df.groupby("corridor").agg(
        hotspot_id=("hotspot_id", dominant(-1, ignore=(-1,))),
        congestion_index=("congestion_index", "mean"),
        corridor_centrality_max=("corridor_centrality_max", "max"),
        cause_severity=("cause_severity", "mean"),
        road_closure=("road_closure", "mean"),
        incident_density_24h=("incident_density_24h", "mean"),
        veh_type=("veh_type", dominant("unknown", ignore=("unknown",))),
        nlp_severity_score=("nlp_severity_score", "mean"),
        description_length=("description_length", "mean"),
        has_kannada=("has_kannada", lambda s: int(s.mean() > 0.5)),
        reason_breakdown_clean=("reason_breakdown_clean", dominant("none", ignore=("none",))),
    )
    return agg


def _corridor_row(corridor):
    agg = get_corridor_stats()
    if corridor in agg.index:
        return agg.loc[corridor]
    return agg.mean(numeric_only=True)


def _is_peak_hour(hour):
    return 1 if (4 <= hour < 7 or 19 <= hour < 23) else 0


def predict_label(clf, feats):
    """CatBoostClassifier.predict returns a (1,1) object array -- unwrap to a plain str."""
    return str(clf.predict(feats)[0][0])


def build_event_features(corridor, event_type, dt: datetime):
    """Feature row for a corridor under a hypothetical planned event."""
    row = _corridor_row(corridor)
    severity = CAUSE_SEVERITY_BY_EVENT.get(event_type, 3)
    feats = {
        "hour": dt.hour,
        "dayofweek": dt.weekday(),
        "month": dt.month,
        "is_peak_hour": _is_peak_hour(dt.hour),
        "hotspot_id": str(row.get("hotspot_id", -1)),
        "congestion_index": float(row.get("congestion_index", 0.0)),
        "corridor_centrality_max": float(row.get("corridor_centrality_max", 0.0)),
        "cause_severity": severity,
        "road_closure": 1,
        "is_planned": 1,
        "incident_density_24h": float(row.get("incident_density_24h", 0.0)),
        "veh_type": str(row.get("veh_type", "unknown")),
        "nlp_severity_score": float(row.get("nlp_severity_score", 0.0)),
        "description_length": float(row.get("description_length", 0.0)),
        "has_kannada": int(row.get("has_kannada", 0)),
        "reason_breakdown_clean": str(row.get("reason_breakdown_clean", "none")),
    }
    return pd.DataFrame([feats])[FEATURES]


def build_live_features(corridor, now: datetime = None):
    """Feature row for a corridor's current, unplanned baseline state."""
    now = now or datetime.now()
    row = _corridor_row(corridor)
    feats = {
        "hour": now.hour,
        "dayofweek": now.weekday(),
        "month": now.month,
        "is_peak_hour": _is_peak_hour(now.hour),
        "hotspot_id": str(row.get("hotspot_id", -1)),
        "congestion_index": float(row.get("congestion_index", 0.0)),
        "corridor_centrality_max": float(row.get("corridor_centrality_max", 0.0)),
        "cause_severity": float(row.get("cause_severity", 2.0)),
        "road_closure": int(round(row.get("road_closure", 0.0))),
        "is_planned": 0,
        "incident_density_24h": float(row.get("incident_density_24h", 0.0)),
        "veh_type": str(row.get("veh_type", "unknown")),
        "nlp_severity_score": float(row.get("nlp_severity_score", 0.0)),
        "description_length": float(row.get("description_length", 0.0)),
        "has_kannada": int(row.get("has_kannada", 0)),
        "reason_breakdown_clean": str(row.get("reason_breakdown_clean", "none")),
    }
    return pd.DataFrame([feats])[FEATURES]
