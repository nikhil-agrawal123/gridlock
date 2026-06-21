"""Page 1: Live Impact Map -- corridor situational awareness."""
import folium
import requests
import streamlit as st
from streamlit_folium import st_folium

import ui
from config import API_BASE

st.set_page_config(page_title="Live Impact Map", layout="wide")
ui.inject_css()

ui.header(
    "Situational awareness",
    "Live Impact Map",
    "Every monitored corridor's composite risk, refreshed every 15 minutes "
    "from TomTom traffic flow and the breakdown-risk model.",
)


@st.cache_data(ttl=60)
def fetch_states(horizon_min=0):
    if horizon_min <= 0:
        resp = requests.get(f"{API_BASE}/corridors/all", timeout=20)
    else:
        resp = requests.get(f"{API_BASE}/corridors/projected",
                            params={"horizon_min": horizon_min}, timeout=40)
    resp.raise_for_status()
    return resp.json()


HORIZONS = {"Now": 0, "+30 min": 30, "+1 hour": 60, "+2 hours": 120}

head_l, head_r = st.columns([3, 1])
with head_l:
    sel_horizon = st.radio(
        "Outlook", list(HORIZONS), horizontal=True, label_visibility="collapsed",
        help="Project every corridor forward. Live readings are blended toward the "
             "model's forecast for that time — the further out, the more the model leads.",
    )
horizon_min = HORIZONS[sel_horizon]
forecasting = horizon_min > 0
with head_r:
    if st.button("Refresh now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

try:
    states = fetch_states(horizon_min)
except requests.RequestException as e:
    st.error(f"Couldn't reach the API at {API_BASE}: {e}")
    st.stop()

live = bool(states) and not states[0].get("tomtom_is_mock")
high = sum(1 for c in states if c["impact_level"] == "High")
med = sum(1 for c in states if c["impact_level"] == "Medium")
peak = max(states, key=lambda c: c["composite_score"]) if states else None

wx = states[0] if states else {}
wx_live = bool(states) and not wx.get("weather_is_mock")
fc_hour = states[0].get("forecast_hour") if forecasting and states else None
if forecasting:
    ui.pill(f"FORECAST · {sel_horizon} (~{fc_hour:02d}:00)", ui.AMBER)
else:
    ui.pill("TomTom traffic flow · LIVE" if live else "TomTom traffic flow · MOCK",
            ui.GREEN if live else ui.AMBER)
if wx_live and wx.get("weather_condition"):
    ui.pill(f"Weather · {wx['weather_condition']} (×{wx['weather_factor']})", ui.NAVY)

if forecasting:
    pers = states[0].get("live_persistence", 0) if states else 0
    st.info(
        f"Projected **{sel_horizon}** ahead (~{fc_hour:02d}:00). Live speed readings are "
        f"blended **{pers*100:.0f}% live / {(1-pers)*100:.0f}% model forecast** for that "
        f"hour — the further out you look, the more the breakdown-risk model leads. "
        f"Weather held at current; event pressure re-checked for that time."
    )

ui.readouts([
    {"label": "Corridors", "value": len(states), "sub": "monitored", "accent": ui.NAVY},
    {"label": "High impact", "value": high, "sub": "needs attention", "accent": ui.RED},
    {"label": "Medium impact", "value": med, "sub": "watch", "accent": ui.AMBER},
    {"label": "Peak corridor", "value": f"{peak['composite_score']:.0f}" if peak else "—",
     "sub": peak["corridor"] if peak else "", "accent": ui.signal_colour(peak["impact_level"]) if peak else ui.NAVY},
])

# --- map ---
ui.section("Corridor map")
COLOURS = {"High": ui.RED, "Medium": ui.AMBER, "Low": ui.GREEN}


def speed_line(c):
    cur, free = c.get("tomtom_current_speed"), c.get("tomtom_free_flow_speed")
    if cur is not None and free is not None:
        closed = " · ROAD CLOSED" if c.get("tomtom_road_closure") else ""
        return f"<br>Speed: {cur}/{free} km/h{closed}"
    return f"<br>Slowdown: {c['tomtom_deviation']}"


m = folium.Map(location=[12.97, 77.59], zoom_start=12, tiles="cartodbpositron")
for c in states:
    colour = COLOURS.get(c["impact_level"], "gray")
    folium.CircleMarker(
        location=[c["lat"], c["lon"]],
        radius=10, color=colour, weight=2, fill=True, fill_color=colour, fill_opacity=0.85,
        popup=folium.Popup(
            f"<b>{c['corridor']}</b><br>Risk score: {c['composite_score']}/100<br>"
            f"Impact: {c['impact_level']}<br>Est. clearance: {c['congestion_duration_min']} min"
            + speed_line(c)
            + ("<br><i>Event nearby</i>" if c["event_nearby"] else ""),
            max_width=220,
        ),
    ).add_to(m)
st_folium(m, height=480, use_container_width=True)

# --- signature rail ---
ui.section("Corridor status board")
st.caption("Ranked by composite risk score · signal colour = forecast impact level")
ui.corridor_rail(states)

# --- active incidents (Mark Resolved) ---
ui.section("Active incidents")
try:
    active = requests.get(f"{API_BASE}/incidents/active", timeout=10).json()
except requests.RequestException:
    active = []

if active:
    st.caption(f"{len(active)} open incident(s) — mark resolved when the situation clears.")
    for inc in sorted(active, key=lambda x: -x["age_minutes"]):
        col_info, col_btn = st.columns([4, 1])
        with col_info:
            age_h = inc["age_minutes"] / 60
            badge = ui.level_badge("High") if age_h > 4 else (
                ui.level_badge("Medium") if age_h > 1 else ui.level_badge("Low"))
            st.markdown(
                f'{badge} **{inc["corridor"]}** — open for '
                f'{int(inc["age_minutes"])} min '
                f'{"(officer present)" if inc.get("officer_present") else ""}',
                unsafe_allow_html=True,
            )
        with col_btn:
            if st.button("Mark resolved", key=f"resolve_{inc['incident_id']}",
                         use_container_width=True):
                try:
                    r = requests.post(
                        f"{API_BASE}/incident/{inc['incident_id']}/resolve",
                        params={"actual_corridor_count": 1},
                        timeout=10,
                    ).json()
                    st.success(f"✓ {inc['corridor']} resolved — feeds next retrain")
                    st.rerun()
                except requests.RequestException as e:
                    st.error(f"Resolve failed: {e}")
else:
    st.caption("No open incidents.")

# --- explainability ---
ui.section("Why this recommendation?")
st.caption("Two layers of explanation — how the composite score was built, and the model's own reasoning for the impact-level forecast.")
if forecasting:
    st.caption(f"Composite make-up reflects the **{sel_horizon}** projection; the model "
               f"reasoning panel below explains current conditions.")
ranked = sorted(states, key=lambda c: -c["composite_score"])
sel = st.selectbox("Corridor", [c["corridor"] for c in ranked]) if ranked else None

if sel:
    sel_state = next(c for c in states if c["corridor"] == sel)
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Composite score make-up**")
        if sel_state.get("score_breakdown"):
            ui.score_bars(sel, sel_state["composite_score"], sel_state["score_breakdown"])
        else:
            st.caption("No breakdown available.")
    with col_b:
        st.markdown("**Model reasoning · impact forecast**")
        try:
            ex = requests.get(
                f"{API_BASE}/explain/corridor/{requests.utils.quote(sel, safe='')}",
                timeout=20,
            ).json()
            st.markdown(
                f"Forecast {ui.level_badge(ex['predicted_impact'])} "
                f"<span style='color:{ui.STEEL};font-size:.82rem'>· model {ex['model_version']}</span>",
                unsafe_allow_html=True,
            )
            ui.shap_force(ex["contributions"])
        except requests.RequestException as e:
            st.caption(f"Couldn't load model explanation: {e}")

# --- full table ---
ui.section("All corridor readings")
ui.corridor_table(states)
