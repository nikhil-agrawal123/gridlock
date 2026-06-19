"""Day 2.1 -- derive impact_level, congestion_duration_min, affected_corridor_count
from data/processed/clean_featured.parquet. No new API calls: corridor centrality
comes from the already-cached osmnx graph + betweenness pickle from Day 1.
"""
import os
import pickle

import numpy as np
import osmnx as ox
import pandas as pd

DATA_DIR = "data"
PROCESSED_DIR = os.path.join(DATA_DIR, "processed")
GRAPH_PATH = os.path.join(DATA_DIR, "bengaluru_graph.graphml")
BC_PATH = os.path.join(DATA_DIR, "betweenness.pkl")
IN_PATH = os.path.join(PROCESSED_DIR, "clean_featured.parquet")
OUT_PATH = os.path.join(PROCESSED_DIR, "featured_v2.parquet")


def add_corridor_centrality(df: pd.DataFrame) -> pd.DataFrame:
    """Map each incident to its nearest road-network node and take the
    per-corridor max betweenness centrality, same logic as Day 1's
    (disabled) osmnx branch, now backed by the cached graph + centrality."""
    if "corridor_centrality_max" in df.columns:
        return df

    print("Loading cached Bengaluru graph + betweenness centrality...")
    G = ox.load_graphml(GRAPH_PATH)
    with open(BC_PATH, "rb") as f:
        bc = pickle.load(f)

    print("Mapping incidents to nearest road-network nodes (batched)...")
    nodes = ox.distance.nearest_nodes(G, df["longitude"].values, df["latitude"].values)
    df["node_centrality"] = [bc.get(n, 0.0) for n in nodes]
    df["corridor_centrality_max"] = df.groupby("corridor")["node_centrality"].transform("max")
    return df


def derive_targets(df: pd.DataFrame) -> pd.DataFrame:
    # TARGET 1 -- impact_level (Low / Medium / High)
    # Weighted composite: resolution time 50%, road closure 30%, cause severity 20%
    resolution_for_score = df["resolution_min"].fillna(df["resolution_min"].median())
    score = (
        resolution_for_score.clip(0, 500) / 500 * 0.5
        + df["road_closure"] * 0.3
        + (df["cause_severity"] / df["cause_severity"].max()) * 0.2
    )
    df["impact_level"] = pd.cut(
        score, bins=[-0.01, 0.33, 0.66, 1.01], labels=["Low", "Medium", "High"]
    )

    # TARGET 2 -- congestion_duration_min
    # Raw resolution_min has a fat multi-day tail (planned closures, stale
    # records) that swamps a minutes-scale regressor; p99 itself sits at
    # ~50 days so it doesn't actually trim the tail. Cap at 500 min (~8hrs),
    # the same ceiling the impact_level composite score uses, so "duration"
    # stays on the timescale congestion actually resolves on.
    df["congestion_duration_min"] = df["resolution_min"].clip(0, 500)

    # TARGET 3 -- affected_corridor_count
    # High-centrality corridors cascade to more neighbours.
    centrality_norm = df["corridor_centrality_max"] / df["corridor_centrality_max"].max()
    df["affected_corridor_count"] = (
        (centrality_norm * 8).fillna(1).clip(1, 6).round().astype(int)
    )
    return df


def main():
    df = pd.read_parquet(IN_PATH)
    df = add_corridor_centrality(df)
    df = derive_targets(df)
    df.to_parquet(OUT_PATH, index=False)

    print(f"Saved: {OUT_PATH}  shape={df.shape}")
    print(df[["impact_level", "congestion_duration_min", "affected_corridor_count"]].describe(include="all"))
    print("\nimpact_level counts:")
    print(df["impact_level"].value_counts())


if __name__ == "__main__":
    main()
