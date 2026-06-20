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
def fetch_states():
    resp = requests.get(f"{API_BASE}/corridors/all", timeout=20)
    resp.raise_for_status()
    return resp.json()


head_l, head_r = st.columns([3, 1])
with head_r:
    if st.button("Refresh now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

try:
    states = fetch_states()
except requests.RequestException as e:
    st.error(f"Couldn't reach the API at {API_BASE}: {e}")
    st.stop()

live = bool(states) and not states[0].get("tomtom_is_mock")
high = sum(1 for c in states if c["impact_level"] == "High")
med = sum(1 for c in states if c["impact_level"] == "Medium")
peak = max(states, key=lambda c: c["composite_score"]) if states else None

wx = states[0] if states else {}
wx_live = bool(states) and not wx.get("weather_is_mock")
with head_l:
    ui.pill("TomTom traffic flow · LIVE" if live else "TomTom traffic flow · MOCK",
            ui.GREEN if live else ui.AMBER)
    if wx_live and wx.get("weather_condition"):
        ui.pill(f"Weather · {wx['weather_condition']} (×{wx['weather_factor']})", ui.NAVY)

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
ui.section("Why these scores?")
st.caption("Every score decomposes into the factors that built it — live speed, the breakdown-risk model, event context and weather.")
ranked = sorted(states, key=lambda c: -c["composite_score"])
for c in ranked[:5]:
    if c.get("score_breakdown"):
        ui.score_bars(c["corridor"], c["composite_score"], c["score_breakdown"])

# --- full table ---
ui.section("All corridor readings")
ui.corridor_table(states)
