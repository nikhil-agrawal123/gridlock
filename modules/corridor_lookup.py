"""Corridor spatial lookup.

The Astram dataset tags incidents with a named corridor (e.g. "Mysore Road")
but has no corridor polylines/edge lists -- so "which corridor is this graph
node on" is approximated by nearest-centroid: each corridor's centroid is the
mean incident location for that corridor, and a node/point is assigned to
whichever centroid is closest (haversine). This is the same
defensible-approximation tradeoff the blast-radius/BPR model makes.
"""
import math
import os
from functools import lru_cache

import pandas as pd

CLEAN_FEATURED_PATH = os.path.join("data", "processed", "clean_featured.parquet")

# Base officer counts per corridor for the manpower planner, set from the
# Day 1 risk leaderboard: higher historical risk_score -> higher base.
CORRIDOR_BASE = {
    "Non-corridor": 2,
    "CBD 1": 3,
    "CBD 2": 3,
    "Mysore Road": 3,
    "Airport New South Road": 2,
    "Varthur Road": 2,
    "ORR North 1": 2,
    "ORR East 1": 2,
    "Hosur Road": 2,
    "Bellary Road 1": 2,
    "Old Airport Road": 2,
    "IRR(Thanisandra road)": 1,
    "Hennur Main Road": 1,
    "West of Chord Road": 1,
    "Bannerghata Road": 1,
    "Old Madras Road": 1,
    "ORR North 2": 1,
    "Magadi Road": 1,
    "ORR West 1": 1,
    "Bellary Road 2": 1,
    "Tumkur Road": 1,
    "ORR East 2": 1,
}


def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


@lru_cache(maxsize=1)
def get_corridor_centroids():
    """corridor -> (lat, lon) centroid, excluding the 'Non-corridor' bucket."""
    df = pd.read_parquet(CLEAN_FEATURED_PATH)
    df = df[df["corridor"] != "Non-corridor"]
    centroids = df.groupby("corridor")[["latitude", "longitude"]].mean()
    return {c: (row.latitude, row.longitude) for c, row in centroids.iterrows()}


def nearest_corridor(lat, lon):
    centroids = get_corridor_centroids()
    best_corridor, best_dist = None, float("inf")
    for corridor, (clat, clon) in centroids.items():
        d = _haversine_m(lat, lon, clat, clon)
        if d < best_dist:
            best_corridor, best_dist = corridor, d
    return best_corridor


def get_all_corridors():
    """All named corridors with a known centroid (excludes 'Non-corridor')."""
    return sorted(get_corridor_centroids().keys())


def nodes_to_corridors(G, nodes):
    """Map a list of osmnx node ids -> sorted list of unique corridor names."""
    corridors = set()
    for n in nodes:
        data = G.nodes[n]
        corridors.add(nearest_corridor(data["y"], data["x"]))
    return sorted(c for c in corridors if c)
