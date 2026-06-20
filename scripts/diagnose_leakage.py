"""Diagnose data-leakage in the impact_level classifier.

Prints:
  1. Correlation matrix of congestion_index, resolution_min, road_closure, cause_severity
  2. Per-feature AUC (single-feature classifiers) — any feature > 0.95 is a smoking gun
  3. Class distribution of impact_level
  4. CatBoost feature importances from the current trained model

Run:
    python scripts/diagnose_leakage.py
"""
import os
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

# allow imports from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from train_model import CAT_FEATURES, FEATURES

DATA_PATH = os.path.join("data", "processed", "featured_v2.parquet")
MODEL_PATH = os.path.join("models", "current", "impact_clf.pkl")


def main():
    df = pd.read_parquet(DATA_PATH).dropna(subset=["hour", "impact_level"])
    print(f"Loaded {len(df)} rows from {DATA_PATH}\n")

    # ── 1. Correlation matrix ──────────────────────────────────────────
    corr_cols = ["congestion_index", "resolution_min", "road_closure", "cause_severity"]
    available = [c for c in corr_cols if c in df.columns]
    if available:
        print("=" * 60)
        print("1. CORRELATION MATRIX (leak suspects)")
        print("=" * 60)
        print(df[available].corr().round(3).to_string())
        print()

    # ── 2. Class distribution ──────────────────────────────────────────
    print("=" * 60)
    print("2. impact_level CLASS DISTRIBUTION")
    print("=" * 60)
    counts = df["impact_level"].value_counts()
    for level, n in counts.items():
        print(f"  {level:8s}  {n:5d}  ({n / len(df) * 100:5.1f}%)")
    print()

    # ── 3. Per-feature AUC (binary: High vs rest) ─────────────────────
    y_high = (df["impact_level"].astype(str) == "High").astype(int)
    print("=" * 60)
    print("3. SINGLE-FEATURE AUC (High vs rest) — >0.95 = leak")
    print("=" * 60)
    for feat in FEATURES:
        if feat in CAT_FEATURES:
            continue  # skip categoricals for per-feature AUC
        vals = pd.to_numeric(df[feat], errors="coerce")
        mask = vals.notna()
        if mask.sum() < 50:
            continue
        try:
            auc = roc_auc_score(y_high[mask], vals[mask])
            auc = max(auc, 1 - auc)  # direction-agnostic
            flag = " *** LEAK SUSPECT ***" if auc > 0.95 else (
                   " (!) high" if auc > 0.85 else "")
            print(f"  {feat:30s}  AUC={auc:.4f}{flag}")
        except ValueError:
            pass
    print()

    # ── 4. CatBoost feature importances ───────────────────────────────
    if os.path.exists(MODEL_PATH):
        print("=" * 60)
        print("4. CATBOOST FEATURE IMPORTANCES (current production model)")
        print("=" * 60)
        clf = joblib.load(MODEL_PATH)
        try:
            imp = clf.get_feature_importance(prettified=True)
            print(imp.to_string(index=False))
        except Exception as e:
            importances = clf.get_feature_importance()
            names = clf.feature_names_
            for n, v in sorted(zip(names, importances), key=lambda x: -x[1]):
                print(f"  {n:30s}  {v:.2f}")
        print()
    else:
        print(f"(No model found at {MODEL_PATH}, skipping feature importances)\n")

    # ── 5. road_closure → High cross-tab ──────────────────────────────
    if "road_closure" in df.columns:
        print("=" * 60)
        print("5. road_closure vs impact_level CROSS-TAB")
        print("=" * 60)
        ct = pd.crosstab(df["road_closure"], df["impact_level"], margins=True)
        print(ct.to_string())
        print()

    print("Diagnosis complete. If road_closure or cause_severity dominate "
          "importance and/or show AUC > 0.85, that confirms the leakage.\n")


if __name__ == "__main__":
    main()
