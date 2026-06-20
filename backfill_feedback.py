"""Demo aid: seed the feedback store with resolved incidents so the Retrain
button has something to learn from immediately (a fresh deployment has no
feedback until the live loop has run for a while).

Samples rows from featured_v2.parquet and writes each as a matched
prediction + outcome pair, with synthetic timestamps spread over the past
days so the date-partitioning and time-based validation split behave as they
would in production.

    python backfill_feedback.py --n 120
"""
import argparse
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from train_model import CAT_FEATURES, FEATURES

PRED_DIR = Path("data/feedback/predictions")
OUT_DIR = Path("data/feedback/outcomes")


def _feat_dict(row):
    out = {}
    for c in FEATURES:
        v = row[c]
        if c in CAT_FEATURES:
            out[c] = str(v)
        elif pd.isna(v):
            out[c] = None
        else:
            out[c] = float(v)
    return out


def _write_partitioned(records, directory, ts_key):
    directory.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records)
    df["_date"] = pd.to_datetime(df[ts_key]).dt.strftime("%Y-%m-%d")
    for day, grp in df.groupby("_date"):
        grp = grp.drop(columns="_date")
        f = directory / f"{day}.parquet"
        if f.exists():
            grp = pd.concat([pd.read_parquet(f), grp], ignore_index=True)
        grp.to_parquet(f, index=False)


def backfill(n=120, seed=42):
    df = pd.read_parquet("data/processed/featured_v2.parquet").dropna(subset=["hour", "impact_level"])
    sample = df.sample(min(n, len(df)), random_state=seed).reset_index(drop=True)
    base = datetime.now(timezone.utc) - timedelta(days=10)

    preds, outs = [], []
    for i, row in sample.iterrows():
        iid = str(uuid.uuid4())
        pred_at = base + timedelta(minutes=int(i) * 30)
        dur = float(row["congestion_duration_min"]) if not pd.isna(row["congestion_duration_min"]) else 60.0
        resolved_at = pred_at + timedelta(minutes=dur)
        ccount = int(row["affected_corridor_count"]) if not pd.isna(row["affected_corridor_count"]) else 1
        preds.append({
            "incident_id": iid,
            "predicted_at": pred_at.isoformat(),
            "corridor": str(row["corridor"]),
            "feature_snapshot": json.dumps(_feat_dict(row)),
            "predicted_impact_level": str(row["impact_level"]),
            "predicted_duration_min": int(dur),
            "predicted_corridor_count": ccount,
            "composite_score": 0.0,
            "event_context": None,
            "model_version": "backfill",
        })
        outs.append({
            "incident_id": iid,
            "resolved_at": resolved_at.isoformat(),
            "actual_resolution_min": round(dur, 1),
            "actual_impact_level": str(row["impact_level"]),
            "actual_corridor_count": ccount,
            "resolution_method": "backfill",
            "officer_present": False,
        })

    _write_partitioned(preds, PRED_DIR, "predicted_at")
    _write_partitioned(outs, OUT_DIR, "resolved_at")
    return len(sample)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=120)
    args = ap.parse_args()
    print(f"Backfilled {backfill(args.n)} resolved incidents into data/feedback/")
