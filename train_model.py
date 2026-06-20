"""Day 2.2 -- train three CatBoost models on featured_v2.parquet:
  - impact_clf:    classifier  -> impact_level (Low/Medium/High)
  - duration_reg:  regressor   -> congestion_duration_min
  - corridor_reg:  regressor   -> affected_corridor_count
All three share the same 16 features; CAT marks the categorical ones.

Split strategy: TIME-BASED (sort by row order as a time proxy, train on
first 80%, evaluate on last 20%).  Random shuffle is avoided because it
leaks temporal patterns and inflates metrics.
"""
import argparse
import os

import joblib
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor
from sklearn.metrics import accuracy_score, mean_absolute_error, roc_auc_score
from sklearn.preprocessing import label_binarize

DATA_PATH = os.path.join("data", "processed", "featured_v2.parquet")
MODELS_DIR = os.path.join("models", "trained")

FEATURES = [
    "hour", "dayofweek", "month", "is_peak_hour",
    "hotspot_id", "congestion_index", "corridor_centrality_max",
    "cause_severity", "road_closure", "is_planned",
    "incident_density_24h", "veh_type", "nlp_severity_score",
    "description_length", "has_kannada", "reason_breakdown_clean",
]
CAT_FEATURES = ["hotspot_id", "veh_type", "reason_breakdown_clean"]


def load_features():
    df = pd.read_parquet(DATA_PATH).dropna(subset=["hour", "impact_level"])
    X = df[FEATURES].copy()
    for c in CAT_FEATURES:
        X[c] = X[c].astype(str)
    return df, X


def _time_split(X, y, test_frac=0.2):
    """Time-based split: first (1-test_frac) rows train, rest test.
    Rows are assumed to be in chronological order (or a stable proxy)."""
    split = int(len(X) * (1 - test_frac))
    return X.iloc[:split], X.iloc[split:], y.iloc[:split], y.iloc[split:]


def train_impact_classifier(df, X, eval_only=False):
    y = df["impact_level"].astype(str)
    X_tr, X_te, y_tr, y_te = _time_split(X, y)
    clf = CatBoostClassifier(
        iterations=500, depth=6, learning_rate=0.05,
        cat_features=CAT_FEATURES, eval_metric="Accuracy",
        auto_class_weights="Balanced", random_seed=42, verbose=100,
    )
    clf.fit(X_tr, y_tr, eval_set=(X_te, y_te), early_stopping_rounds=50)

    preds = clf.predict(X_te).flatten()
    proba = clf.predict_proba(X_te)
    acc = accuracy_score(y_te, preds)
    try:
        y_bin = label_binarize(y_te, classes=clf.classes_)
        auc = roc_auc_score(y_bin, proba, multi_class="ovr")
    except ValueError:
        auc = float("nan")
    print(f"[impact_clf] accuracy={acc:.4f}  auc_ovr={auc:.4f}")
    if auc > 0.95:
        print("  WARNING: AUC > 0.95 -- possible residual leakage, check feature importances below")

    # Feature importance -- surfaces what is driving predictions
    print("\n[impact_clf] Feature importances:")
    try:
        imp = clf.get_feature_importance(prettified=True)
        print(imp.to_string(index=False))
    except Exception:
        for n, v in sorted(zip(clf.feature_names_, clf.get_feature_importance()),
                           key=lambda x: -x[1]):
            print(f"  {n:30s}  {v:.2f}")
    print()

    if not eval_only:
        joblib.dump(clf, os.path.join(MODELS_DIR, "impact_clf.pkl"))
    return clf


def train_duration_regressor(df, X, eval_only=False):
    mask = df["congestion_duration_min"].notna()
    Xd, yd = X[mask], df.loc[mask, "congestion_duration_min"]
    X_tr, X_te, y_tr, y_te = _time_split(Xd, yd)
    reg = CatBoostRegressor(
        iterations=500, depth=6, learning_rate=0.05,
        cat_features=CAT_FEATURES, eval_metric="MAE",
        random_seed=42, verbose=100,
    )
    reg.fit(X_tr, y_tr)

    mae = mean_absolute_error(y_te, reg.predict(X_te))
    print(f"[duration_reg] MAE={mae:.2f} min")

    if not eval_only:
        joblib.dump(reg, os.path.join(MODELS_DIR, "duration_reg.pkl"))
    return reg


def train_corridor_regressor(df, X, eval_only=False):
    y = df["affected_corridor_count"]
    X_tr, X_te, y_tr, y_te = _time_split(X, y)
    reg = CatBoostRegressor(
        iterations=300, depth=4, learning_rate=0.05,
        cat_features=CAT_FEATURES, random_seed=42, verbose=0,
    )
    reg.fit(X_tr, y_tr)

    mae = mean_absolute_error(y_te, reg.predict(X_te))
    print(f"[corridor_reg] MAE={mae:.2f} corridors")

    if not eval_only:
        joblib.dump(reg, os.path.join(MODELS_DIR, "corridor_reg.pkl"))
    return reg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval", action="store_true", help="train+eval only, skip saving")
    args = parser.parse_args()

    os.makedirs(MODELS_DIR, exist_ok=True)
    df, X = load_features()
    print(f"Training rows: {len(df)}  features: {len(FEATURES)}")

    train_impact_classifier(df, X, eval_only=args.eval)
    train_duration_regressor(df, X, eval_only=args.eval)
    train_corridor_regressor(df, X, eval_only=args.eval)
    print("All models trained" + (" (eval-only, not saved)." if args.eval else " and saved."))


if __name__ == "__main__":
    main()
