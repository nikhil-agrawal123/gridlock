"""Per-prediction explainability for the impact classifier.

The Live Map already explains the *composite score* (live speed vs model vs
event vs weather). This goes one level deeper and explains the *model's own*
call: for a given corridor, which input features pushed the impact_level
forecast toward "High" and which pulled it down -- using exact SHAP values
from CatBoost (`get_feature_importance(type="ShapValues")`), not a proxy.

SHAP values are additive: base_value + sum(contributions) = the raw model
score for the explained class, so the bars literally add up to the decision.
"""
from catboost import Pool

from modules import model_registry as mr
from train_model import CAT_FEATURES, FEATURES

# Human-readable labels so the panel doesn't show raw column names.
FEATURE_LABELS = {
    "hour": "Hour of day",
    "dayofweek": "Day of week",
    "month": "Month",
    "is_peak_hour": "Peak-hour window",
    "hotspot_id": "Incident hotspot cluster",
    "congestion_index": "Baseline congestion index",
    "corridor_centrality_max": "Corridor centrality",
    "cause_severity": "Typical cause severity",
    "road_closure": "Road-closure history",
    "is_planned": "Planned event",
    "incident_density_24h": "Recent incident density (24h)",
    "veh_type": "Dominant vehicle type",
    "nlp_severity_score": "Report severity (NLP)",
    "description_length": "Report detail length",
    "has_kannada": "Kannada in reports",
    "reason_breakdown_clean": "Breakdown cause",
}


def _high_index(clf):
    classes = [str(c) for c in clf.classes_]
    return classes.index("High") if "High" in classes else len(classes) - 1


def explain_impact(feats_df, top_k=6):
    """Explain the 'High impact' forecast for a single feature row.

    Returns base value, the predicted label, and the top_k features ranked by
    absolute SHAP contribution, each tagged as pushing impact up or down.
    """
    clf = mr.get_impact_clf()
    pool = Pool(feats_df[FEATURES], cat_features=CAT_FEATURES)
    shap = clf.get_feature_importance(type="ShapValues", data=pool)

    # Shape is (n_obj, n_features+1) for binary / single-class output, or
    # (n_obj, n_classes, n_features+1) for multiclass. Normalise to the row +
    # class we care about ("High").
    row = shap[0]
    if row.ndim == 2:                       # multiclass: (n_classes, n_features+1)
        row = row[_high_index(clf)]
    base_value = float(row[-1])
    raw = row[:-1]

    values = feats_df[FEATURES].iloc[0]
    contribs = [
        {
            "feature": FEATURES[i],
            "label": FEATURE_LABELS.get(FEATURES[i], FEATURES[i]),
            "value": _fmt(values[FEATURES[i]]),
            "contribution": round(float(raw[i]), 4),
            "direction": "up" if raw[i] >= 0 else "down",
        }
        for i in range(len(FEATURES))
    ]
    contribs.sort(key=lambda c: -abs(c["contribution"]))

    predicted = str(clf.predict(feats_df[FEATURES])[0][0])
    return {
        "predicted_impact": predicted,
        "base_value": round(base_value, 4),
        "contributions": contribs[:top_k],
    }


def _fmt(v):
    try:
        f = float(v)
        return int(f) if f == int(f) else round(f, 2)
    except (TypeError, ValueError):
        return str(v)
