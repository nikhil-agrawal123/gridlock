"""Day 3.3 -- Fusion scoring: combine TomTom live deviation, model risk,
event context and weather into one 0-100 composite score per corridor.

Starts on fixed weights (40/35/15/10); once enough live-vs-actual outcome
data has been logged, `LearnedFusionMLP` can be trained to replace the
fixed split with weights learned per condition.
"""
import os

import joblib
import numpy as np

FUSION_MODEL_PATH = os.path.join("models", "trained", "fusion_mlp.pkl")


def compute_score_fixed(tomtom_dev, model_risk, event_mult=1.0, weather=1.0):
    """tomtom_dev, model_risk in [0,1]; event_mult/weather are >=1 multipliers."""
    return round(
        (
            tomtom_dev * 0.40
            + model_risk * 0.35
            + (event_mult - 1) * 0.15
            + (weather - 1) * 0.10
        )
        * 100,
        1,
    )


def score_breakdown(tomtom_dev, model_risk, event_mult=1.0, weather=1.0):
    """Decompose the fixed-weight composite score into its contributing
    factors so the dashboard can explain *why* a corridor scores as it does.
    Shares the exact weights of compute_score_fixed, so the parts always add
    up to that score. Each component's `points` are out of 100."""
    comps = [
        ("Live speed reduction", max(0.0, tomtom_dev) * 0.40),
        ("Breakdown-risk model", max(0.0, model_risk) * 0.35),
        ("Event context", max(0.0, event_mult - 1) * 0.15),
        ("Weather", max(0.0, weather - 1) * 0.10),
    ]
    components = [{"factor": name, "points": round(v * 100, 1)} for name, v in comps]
    total = round(sum(c["points"] for c in components), 1)
    for c in components:
        c["share"] = round(c["points"] / total * 100) if total else 0
    return {"total": total, "components": components}


class LearnedFusionMLP:
    FEATURE_ORDER = [
        "tomtom_deviation", "model_risk", "event_multiplier",
        "weather_factor", "hour_sin", "hour_cos", "is_peak_hour",
    ]

    def __init__(self):
        self.mlp = None

    def train(self, df):
        from sklearn.neural_network import MLPRegressor

        X = df[self.FEATURE_ORDER]
        y = df["congestion_duration_min"] / df["congestion_duration_min"].max()
        self.mlp = MLPRegressor(
            hidden_layer_sizes=(32, 16), activation="relu",
            max_iter=500, random_state=42,
        )
        self.mlp.fit(X, y)
        os.makedirs(os.path.dirname(FUSION_MODEL_PATH), exist_ok=True)
        joblib.dump(self.mlp, FUSION_MODEL_PATH)

    def load(self):
        self.mlp = joblib.load(FUSION_MODEL_PATH)
        return self

    def predict_score(self, tomtom_dev, model_risk, event_mult, weather, hour):
        hour_sin = np.sin(2 * np.pi * hour / 24)
        hour_cos = np.cos(2 * np.pi * hour / 24)
        is_peak = 1 if (4 <= hour < 7 or 19 <= hour < 23) else 0
        feats = [[tomtom_dev, model_risk, event_mult, weather, hour_sin, hour_cos, is_peak]]
        return round(float(self.mlp.predict(feats)[0]) * 100, 1)


def compute_score(tomtom_dev, model_risk, event_mult=1.0, weather=1.0, hour=None):
    """Uses the learned MLP if a trained fusion_mlp.pkl exists, else falls
    back to the fixed-weight formula."""
    if os.path.exists(FUSION_MODEL_PATH) and hour is not None:
        try:
            mlp = LearnedFusionMLP().load()
            return mlp.predict_score(tomtom_dev, model_risk, event_mult, weather, hour)
        except Exception:
            pass
    return compute_score_fixed(tomtom_dev, model_risk, event_mult, weather)
