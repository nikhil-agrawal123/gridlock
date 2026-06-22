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


# Officer-report dropdowns -- the categories the model was trained on.
CAUSES = [
    "general_breakdown", "engine_problem", "brake_problem", "tyre_puncture",
    "tyre_burst", "electrical_problem", "mechanical_problem", "gear_problem",
    "clutch_problem", "steering_problem", "off_road", "diesel_empty",
    "battery_problem", "oil_leak", "other",
]
VEH_TYPES = [
    "private_car", "bmtc_bus", "ksrtc_bus", "private_bus", "auto", "taxi",
    "truck", "heavy_vehicle", "lcv", "others", "unknown",
]


@st.cache_data(ttl=10)
def fetch_info():
    return requests.get(f"{API_BASE}/model-info").json()


@st.cache_data(ttl=300)
def fetch_corridors():
    return requests.get(f"{API_BASE}/corridors/names").json().get("corridors", [])


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
ui.section("Log a past incident")
st.caption(
    "Officers can record an incident the automatic tracker missed — what went "
    "wrong and where. It's stored as a labelled, ground-truth example that the "
    "next retrain learns from, alongside the auto-collected feedback."
)

try:
    corridors = fetch_corridors()
except requests.RequestException:
    corridors = []

if not corridors:
    st.info("Couldn't load the corridor list, so manual reporting is unavailable right now.")
else:
    with st.form("officer_report", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        r_corridor = c1.selectbox("Corridor (where)", corridors)
        r_cause = c2.selectbox("What went wrong", CAUSES)
        r_veh = c3.selectbox("Vehicle involved", VEH_TYPES)

        c4, c5, c6 = st.columns(3)
        r_sev = c4.slider("Severity", 1, 5, 3, help="1 = minor, 5 = severe")
        r_dur = c5.number_input("Minutes to clear", min_value=1, max_value=1440, value=60)
        r_aff = c6.number_input("Corridors affected", min_value=1, max_value=20, value=1)

        c7, c8 = st.columns(2)
        r_closed = c7.checkbox("Road fully closed")
        r_planned = c8.checkbox("Planned / known event")

        r_when = st.text_input(
            "Started at (optional, YYYY-MM-DD HH:MM)", "",
            help="Leave blank to assume it started this many minutes ago.",
        )
        r_notes = st.text_area("Notes (what happened)", "")
        submitted = st.form_submit_button("Submit report", type="primary")

    if submitted:
        payload = {
            "corridor": r_corridor, "cause": r_cause, "veh_type": r_veh,
            "cause_severity": int(r_sev), "road_closure": bool(r_closed),
            "is_planned": bool(r_planned), "duration_min": float(r_dur),
            "corridors_affected": int(r_aff), "notes": r_notes,
        }
        if r_when.strip():
            payload["started_at"] = r_when.strip()
        try:
            res = requests.post(f"{API_BASE}/incident/report", json=payload)
            if res.status_code >= 400:
                detail = res.json().get("detail", res.text)
                st.error(f"Report rejected: {detail}")
            else:
                res = res.json()
                st.cache_data.clear()
                actual = res["actual_impact_level"]
                pred = res.get("predicted")
                if pred:
                    agree = "✓ matched" if pred["impact_level"] == actual else "✗ missed"
                    st.success(
                        f"Logged on **{res['corridor']}** — observed impact **{actual}** "
                        f"({res['actual_resolution_min']:.0f} min). The current model would "
                        f"have predicted **{pred['impact_level']}** ({agree}). "
                        f"Now {res['resolved_incidents']} resolved incidents available to retrain."
                    )
                else:
                    st.success(
                        f"Logged on **{res['corridor']}** — observed impact **{actual}** "
                        f"({res['actual_resolution_min']:.0f} min). "
                        f"Now {res['resolved_incidents']} resolved incidents available to retrain."
                    )
        except requests.RequestException as e:
            st.error(f"Couldn't submit the report: {e}")

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
