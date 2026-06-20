"""Retraining pipeline -- the learning half of the feedback loop.

Merges the prediction + outcome feedback snapshots into labelled rows,
combines them with the original training set, trains candidate CatBoost
models, and promotes the candidate only if it does not regress against the
current production model on a time-based holdout. Never deploys blind.

Run via the /retrain endpoint (Analytics "Retrain" button) or directly:
    python retrain.py
"""
import glob
import json

import joblib
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor
from sklearn.metrics import mean_absolute_error, roc_auc_score
from sklearn.model_selection import train_test_split

from modules import model_registry as mr
from train_model import CAT_FEATURES, FEATURES

FEATURED_PATH = "data/processed/featured_v2.parquet"
MERGED_PATH = "data/feedback/merged_training_log.parquet"
MIN_RESOLVED = 20            # don't bother retraining on a handful of rows
MAX_AUC_DROP = 0.02         # promotion guardrails
MAX_MAE_FACTOR = 1.02


def _read_dir(pattern):
    files = glob.glob(pattern)
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def _prep_X(df):
    X = df[FEATURES].copy()
    for c in CAT_FEATURES:
        X[c] = X[c].astype(str)
    return X


def run_retrain():
    # STEP 1-2 -- merge predictions + outcomes, keep only resolved incidents
    preds = _read_dir("data/feedback/predictions/*.parquet")
    outs = _read_dir("data/feedback/outcomes/*.parquet")
    if preds.empty or outs.empty:
        return {"status": "skipped", "reason": "no feedback collected yet"}

    merged = preds.merge(outs, on="incident_id", how="inner")
    if len(merged) < MIN_RESOLVED:
        return {"status": "skipped",
                "reason": f"only {len(merged)} resolved incidents (need {MIN_RESOLVED})"}
    merged.to_parquet(MERGED_PATH, index=False)

    # STEP 3 -- expand the feature snapshot JSON back into model columns and
    # attach the ACTUAL (ground-truth) labels.
    feat_rows = [json.loads(s) for s in merged["feature_snapshot"]]
    feat_df = pd.DataFrame(feat_rows)
    feat_df["impact_level"] = merged["actual_impact_level"].values
    feat_df["congestion_duration_min"] = merged["actual_resolution_min"].values
    feat_df["affected_corridor_count"] = merged["actual_corridor_count"].values
    feat_df["predicted_at"] = merged["predicted_at"].values
    for c in FEATURES:
        if c not in feat_df.columns:
            feat_df[c] = None

    # STEP 4 -- combine with the original training set (keep history)
    original = pd.read_parquet(FEATURED_PATH).dropna(subset=["hour", "impact_level"])
    original = original[[c for c in FEATURES if c in original.columns]
                        + ["impact_level", "congestion_duration_min", "affected_corridor_count"]].copy()
    original["predicted_at"] = ""  # original rows sort first (oldest)
    combined = pd.concat([original, feat_df], ignore_index=True)
    combined = combined.dropna(subset=["impact_level"])

    # STEP 5 -- train candidate models (same config as train_model.py)
    Xc = _prep_X(combined)
    new_clf = CatBoostClassifier(iterations=500, depth=6, learning_rate=0.05,
                                 cat_features=CAT_FEATURES, auto_class_weights="Balanced",
                                 random_seed=42, verbose=0)
    new_clf.fit(Xc, combined["impact_level"].astype(str))

    dmask = combined["congestion_duration_min"].notna()
    new_reg = CatBoostRegressor(iterations=500, depth=6, learning_rate=0.05,
                                cat_features=CAT_FEATURES, random_seed=42, verbose=0)
    new_reg.fit(Xc[dmask.values], combined.loc[dmask, "congestion_duration_min"])

    new_corr = CatBoostRegressor(iterations=300, depth=4, learning_rate=0.05,
                                 cat_features=CAT_FEATURES, random_seed=42, verbose=0)
    new_corr.fit(Xc, combined["affected_corridor_count"].fillna(1))

    return _validate_and_promote(new_clf, new_reg, new_corr, combined, len(merged))


def _auc_mae(clf, reg, val, Xv):
    classes = list(clf.classes_)
    auc = float(roc_auc_score((val["impact_level"] == "High").astype(int),
                              clf.predict_proba(Xv)[:, classes.index("High")]))
    dmask = val["congestion_duration_min"].notna()
    mae = float(mean_absolute_error(val.loc[dmask, "congestion_duration_min"],
                                    reg.predict(Xv[dmask.values])))
    return round(auc, 3), round(mae, 1)


def _validate_and_promote(new_clf, new_reg, new_corr, combined, n_feedback):
    # Time-based holdout: most recent 15% (feedback rows sort last).
    combined = combined.sort_values("predicted_at").reset_index(drop=True)
    split = int(len(combined) * 0.85)
    val = combined.iloc[split:]
    Xv = _prep_X(val)

    # Score BOTH the candidate and the current production model on the SAME
    # held-out slice -- a fair, apples-to-apples comparison.
    new_auc, new_mae = _auc_mae(new_clf, new_reg, val, Xv)
    cur_auc, cur_mae = _auc_mae(mr.get_impact_clf(), mr.get_duration_reg(), val, Xv)
    new_metrics = {"auc": new_auc, "mae": new_mae, "n_train": int(len(combined))}

    # Sanity guard: suspiciously high AUC likely means residual leakage
    if new_auc > 0.95:
        import logging
        logging.getLogger("trafficsense.retrain").warning(
            "Candidate AUC %.3f > 0.95 -- possible data leakage. "
            "Check feature importances and target derivation.", new_auc)
        new_metrics["auc_warning"] = "suspiciously_high"

    # Feature importances -- saved for audit trail
    try:
        feat_imp = new_clf.get_feature_importance(prettified=True)
        new_metrics["top_features"] = [
            {"feature": row["Feature Id"], "importance": round(row["Importances"], 2)}
            for _, row in feat_imp.head(5).iterrows()
        ]
    except Exception:
        pass

    models = {"impact_clf": new_clf, "duration_reg": new_reg, "corridor_reg": new_corr}

    if new_auc >= cur_auc - MAX_AUC_DROP and new_mae <= cur_mae * MAX_MAE_FACTOR:
        version_id = mr.promote(models, new_metrics, n_feedback)
        return {"status": "promoted", "version": version_id, **new_metrics,
                "previous": {"auc": cur_auc, "mae": cur_mae}}

    # Rejected: archive the candidate so it's inspectable but not deployed.
    import shutil
    from pathlib import Path
    cand = Path("models/versions/_rejected_candidate")
    cand.mkdir(parents=True, exist_ok=True)
    for name, m in models.items():
        joblib.dump(m, cand / mr.MODEL_FILES[name])
    (cand / "metrics.json").write_text(json.dumps(new_metrics, indent=2))
    return {"status": "rejected", "reason": "regressed vs current model",
            "candidate": new_metrics, "current": {"auc": cur_auc, "mae": cur_mae}}


if __name__ == "__main__":
    mr.seed_if_needed()
    print(json.dumps(run_retrain(), indent=2))
