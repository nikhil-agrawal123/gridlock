"""Historical blockage predictor.

Separate from the geometric blast-radius / model prediction: this looks only
at *what has historically gone wrong* near a venue at the event's time of
day, straight from the Astram incident record. Two views:

  - corridors:  ranked by historical blockage likelihood (incident
                frequency x closure rate x cause severity) near the venue
                at a similar hour.
  - hotspots:   the HDBSCAN incident clusters near the venue active at that
                time -- specific intersection-level blackspots, as points.

It answers "where do breakdowns and closures actually happen around here
during events like this," independent of the road-network blast radius.
"""
import math
from functools import lru_cache

import numpy as np
import pandas as pd

FEATURED_PATH = "data/processed/featured_v2.parquet"


@lru_cache(maxsize=1)
def _df():
    df = pd.read_parquet(FEATURED_PATH)
    return df[df["latitude"].notna() & df["longitude"].notna()].copy()


def _haversine_km(lat, lon, lats, lons):
    R = 6371.0
    p1 = math.radians(lat)
    p2 = np.radians(lats)
    dphi = np.radians(lats - lat)
    dlmb = np.radians(lons - lon)
    a = np.sin(dphi / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def predict_blockages(lat, lon, when, radius_km, top_corridors=6, top_hotspots=5):
    """Returns {corridors:[{corridor, likelihood, incidents, closure_rate,
    avg_severity}], hotspots:[{lat, lon, incidents, closure_rate}]}."""
    df = _df()
    dist = _haversine_km(lat, lon, df["latitude"].values, df["longitude"].values)
    near = df[dist <= max(radius_km, 1.5)]
    if near.empty:
        return {"corridors": [], "hotspots": []}

    # Time-of-day pattern: incidents within +/-1 hour of the event hour
    # (wrapping midnight), which is when this event's traffic would be present.
    hour = when.hour
    hdiff = (near["hour"] - hour).abs()
    hdiff = np.minimum(hdiff, 24 - hdiff)
    at_time = near[hdiff <= 1]
    if at_time.empty:
        at_time = near  # fall back to all-day pattern if nothing at this hour

    # --- corridor ranking ---
    g = at_time.groupby("corridor").agg(
        incidents=("corridor", "size"),
        closure_rate=("road_closure", "mean"),
        avg_severity=("cause_severity", "mean"),
    )
    g = g[g.index != "Non-corridor"]
    if not g.empty:
        freq = g["incidents"] / g["incidents"].max()
        g["likelihood"] = (freq * (1 + g["closure_rate"]) * (g["avg_severity"] / 5)).round(3)
        g = g.sort_values("likelihood", ascending=False).head(top_corridors)
    corridors = [
        {
            "corridor": idx,
            "likelihood": float(row["likelihood"]),
            "incidents": int(row["incidents"]),
            "closure_rate": round(float(row["closure_rate"]), 2),
            "avg_severity": round(float(row["avg_severity"]), 1),
        }
        for idx, row in g.iterrows()
    ] if not g.empty else []

    # --- HDBSCAN hotspots (intersection-level blackspots) ---
    clustered = at_time[at_time["hotspot_id"] >= 0]
    hotspots = []
    if not clustered.empty:
        h = clustered.groupby("hotspot_id").agg(
            lat=("latitude", "mean"),
            lon=("longitude", "mean"),
            incidents=("hotspot_id", "size"),
            closure_rate=("road_closure", "mean"),
        ).sort_values("incidents", ascending=False).head(top_hotspots)
        hotspots = [
            {
                "lat": round(float(row["lat"]), 5),
                "lon": round(float(row["lon"]), 5),
                "incidents": int(row["incidents"]),
                "closure_rate": round(float(row["closure_rate"]), 2),
            }
            for _, row in h.iterrows()
        ]

    return {"corridors": corridors, "hotspots": hotspots}
