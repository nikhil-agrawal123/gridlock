"""Page 5: Analytics & Model Retrain -- the feedback-loop control panel.

Shows the current model's metrics and how many resolved incidents have
accumulated, lets an operator trigger a retrain (which only promotes a new
model if it beats the current one), and lists the full version history with
one-click rollback.
"""
import requests
import streamlit as st

import ui
from config import API_BASE

st.set_page_config(page_title="Analytics & Retrain", layout="wide")
ui.inject_css()

ui.header(
    "Model operations",
    "Analytics & Retrain",
    "Every incident TrafficSense resolves becomes a labelled training example. "
    "Retrain merges that feedback, trains a candidate, and only promotes it if "
    "it beats the current model — so the model never silently gets worse.",
)


@st.cache_data(ttl=10)
def fetch_info():
    return requests.get(f"{API_BASE}/model-info").json()


try:
    info = fetch_info()
except requests.RequestException as e:
    st.error(f"Couldn't reach the API at {API_BASE}: {e}")
    st.stop()

m = info["metrics"]
ui.readouts([
    {"label": "Active model", "value": info["current"] or "—", "accent": ui.NAVY},
    {"label": "AUC-ROC (High)", "value": f"{m.get('auc', 0):.3f}", "accent": ui.GREEN},
    {"label": "Duration MAE", "value": f"{m.get('mae', 0):.1f} min", "accent": ui.NAVY},
    {"label": "Training records", "value": m.get("n_train", 0), "accent": ui.NAVY},
    {"label": "Resolved incidents", "value": info["resolved_incidents"],
     "sub": "available as feedback", "accent": ui.AMBER},
])

st.markdown('<hr class="ts-rule"/>', unsafe_allow_html=True)
ui.section("Retrain")
pending = info["resolved_incidents"] - info.get("feedback_used_at_last_retrain", 0)
st.caption(f"{max(0, pending)} new resolved incidents since the last retrain.")

if st.button("Retrain model now", type="primary"):
    with st.spinner("Merging feedback, training candidate, validating against the current model..."):
        try:
            result = requests.post(f"{API_BASE}/retrain").json()
        except requests.RequestException as e:
            st.error(f"Retrain request failed: {e}")
            st.stop()
    st.cache_data.clear()

    status = result.get("status")
    if status == "promoted":
        st.success(
            f"New model **{result['version']}** promoted — AUC {result['auc']:.3f} "
            f"(was {result['previous']['auc']:.3f}), MAE {result['mae']:.1f} min "
            f"(was {result['previous']['mae']:.1f})."
        )
        st.balloons()
    elif status == "rejected":
        st.warning(
            f"Candidate **rejected** — it regressed vs the current model "
            f"(candidate AUC {result['candidate']['auc']:.3f} / MAE {result['candidate']['mae']:.1f} "
            f"vs current {result['current']['auc']:.3f} / {result['current']['mae']:.1f}). "
            "Current model kept in production."
        )
    else:
        st.info(result.get("reason", "Nothing to retrain."))

st.markdown('<hr class="ts-rule"/>', unsafe_allow_html=True)
ui.section("Version history")
versions = sorted(info["versions"], key=lambda v: v["version"], reverse=True)
st.dataframe(
    [{"Version": v["version"], "AUC": v.get("auc"), "MAE (min)": v.get("mae"),
      "Train records": v.get("n_train"), "Promoted at": v.get("promoted_at", "")[:19]}
     for v in versions],
    use_container_width=True, hide_index=True,
)

if len(versions) > 1:
    with st.expander("Roll back to an earlier version"):
        target = st.selectbox("Version", [v["version"] for v in versions])
        if st.button("Roll back"):
            try:
                r = requests.post(f"{API_BASE}/rollback/{target}").json()
                st.cache_data.clear()
                if r.get("status") == "rolled_back":
                    st.success(f"Rolled back — active model is now {r['current']}.")
                else:
                    st.error(r.get("detail", "Rollback failed."))
            except requests.RequestException as e:
                st.error(f"Rollback failed: {e}")
