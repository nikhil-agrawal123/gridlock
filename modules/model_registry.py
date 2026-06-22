"""Model registry -- versioning, promotion and hot-reload for the retrain loop.

The active models live in models/current/ and are what the API serves. Every
promoted model is also archived under models/versions/<date>_v<n>/ with its
own metrics.json, and models/registry.json tracks the current pointer + full
history. Old versions are never deleted, so a bad retrain can be rolled back
with one call.

The API loads models through get_impact_clf()/get_duration_reg()/
get_corridor_reg(); after a promotion the /retrain endpoint calls reload()
so the new model is served without a restart.
"""
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import joblib

PREDICT_THREADS = int(os.environ.get("CATBOOST_PREDICT_THREADS", "1"))

MODELS_DIR = Path("models")
TRAINED_DIR = MODELS_DIR / "trained"      # original Day-2 build artifacts
CURRENT_DIR = MODELS_DIR / "current"      # active models the API serves
VERSIONS_DIR = MODELS_DIR / "versions"
REGISTRY_PATH = MODELS_DIR / "registry.json"

MODEL_FILES = {
    "impact_clf": "impact_clf.pkl",
    "duration_reg": "duration_reg.pkl",
    "corridor_reg": "corridor_reg.pkl",
}

_cache = {}  # name -> loaded model


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def read_registry() -> dict:
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text())
    return {"current": None, "versions": []}


def _write_registry(reg: dict):
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2))


def next_version_id() -> str:
    reg = read_registry()
    n = len(reg["versions"]) + 1
    return f"{datetime.now(timezone.utc):%Y-%m-%d}_v{n}"


def seed_if_needed():
    """First run: copy the Day-2 models into current/ + versions/<date>_v1,
    compute baseline metrics, and write the registry. Idempotent."""
    if REGISTRY_PATH.exists():
        return
    version_id = f"{datetime.now(timezone.utc):%Y-%m-%d}_v1"
    vdir = VERSIONS_DIR / version_id
    vdir.mkdir(parents=True, exist_ok=True)
    CURRENT_DIR.mkdir(parents=True, exist_ok=True)

    for fname in MODEL_FILES.values():
        src = TRAINED_DIR / fname
        if src.exists():
            shutil.copy(src, vdir / fname)
            shutil.copy(src, CURRENT_DIR / fname)

    metrics = _baseline_metrics()
    (vdir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    _write_registry({
        "current": version_id,
        "versions": [{"version": version_id, "promoted_at": _now_iso(), **metrics}],
        "feedback_used": 0,
    })


def _baseline_metrics() -> dict:
    """AUC (High vs rest) + duration MAE on a time-based holdout of
    featured_v2, so the Analytics page has real numbers for the seeded v1."""
    try:
        import pandas as pd
        from sklearn.metrics import mean_absolute_error, roc_auc_score

        from train_model import CAT_FEATURES, FEATURES

        df = pd.read_parquet("data/processed/featured_v2.parquet").dropna(subset=["hour", "impact_level"])
        X = df[FEATURES].copy()
        for c in CAT_FEATURES:
            X[c] = X[c].astype(str)
        # Time-based split: last 20% as test (consistent with train_model.py)
        split = int(len(X) * 0.8)
        X_te = X.iloc[split:]
        te = df.iloc[split:]
        clf = joblib.load(CURRENT_DIR / "impact_clf.pkl")
        reg = joblib.load(CURRENT_DIR / "duration_reg.pkl")
        classes = list(clf.classes_)
        proba_high = clf.predict_proba(X_te, thread_count=PREDICT_THREADS)[:, classes.index("High")]
        auc = float(roc_auc_score((te["impact_level"] == "High").astype(int), proba_high))
        dmask = te["congestion_duration_min"].notna()
        mae = float(mean_absolute_error(te.loc[dmask, "congestion_duration_min"],
                                        reg.predict(X_te[dmask.values], thread_count=PREDICT_THREADS)))
        return {"auc": round(auc, 3), "mae": round(mae, 1), "n_train": int(len(df))}
    except Exception:
        return {"auc": 0.0, "mae": 0.0, "n_train": 0}


# --- model access (hot-reloadable) ---------------------------------------
def _load(name):
    if name not in _cache:
        _cache[name] = joblib.load(CURRENT_DIR / MODEL_FILES[name])
    return _cache[name]


def get_impact_clf():
    return _load("impact_clf")


def get_duration_reg():
    return _load("duration_reg")


def get_corridor_reg():
    return _load("corridor_reg")


def reload():
    """Drop the cache so the next access reloads the freshly promoted models."""
    _cache.clear()


def current_version() -> str:
    return read_registry().get("current") or "unversioned"


def current_metrics() -> dict:
    reg = read_registry()
    for v in reg["versions"]:
        if v["version"] == reg["current"]:
            return v
    return {"auc": 0.0, "mae": 0.0, "n_train": 0}


# --- promotion / rollback ------------------------------------------------
def promote(models: dict, metrics: dict, feedback_used: int) -> str:
    """Archive `models` (name->fitted estimator) as a new version and make it
    current. Returns the new version id."""
    version_id = next_version_id()
    vdir = VERSIONS_DIR / version_id
    vdir.mkdir(parents=True, exist_ok=True)
    CURRENT_DIR.mkdir(parents=True, exist_ok=True)

    for name, model in models.items():
        joblib.dump(model, vdir / MODEL_FILES[name])
        joblib.dump(model, CURRENT_DIR / MODEL_FILES[name])
    (vdir / "metrics.json").write_text(json.dumps(metrics, indent=2))

    reg = read_registry()
    reg["current"] = version_id
    reg["versions"].append({"version": version_id, "promoted_at": _now_iso(), **metrics})
    reg["feedback_used"] = feedback_used
    _write_registry(reg)
    reload()
    return version_id


def rollback_to(version_id: str) -> bool:
    vdir = VERSIONS_DIR / version_id
    if not vdir.exists():
        return False
    for fname in MODEL_FILES.values():
        if (vdir / fname).exists():
            shutil.copy(vdir / fname, CURRENT_DIR / fname)
    reg = read_registry()
    reg["current"] = version_id
    _write_registry(reg)
    reload()
    return True
