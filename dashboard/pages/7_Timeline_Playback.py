"""Page 7: Timeline Playback -- scrub or play through a model-forecast day and
watch every corridor's predicted risk rise and fall hour by hour. Pure model
output (no live TomTom), so it always runs and shows the model's learned
daily rhythm."""
import time

import folium
import requests
import streamlit as st
from streamlit_folium import st_folium

import ui
from config import API_BASE

st.set_page_config(page_title="Timeline Playback", layout="wide")
ui.inject_css()

ui.header(
    "Forecast · playback",
    "Timeline Playback",
    "A model-forecast day across the network. Scrub the hour or press play to "
    "watch predicted corridor risk evolve through the morning and evening peaks.",
)

PLAY_SPEED_S = 0.7


@st.cache_data(ttl=300)
def fetch_timeline():
    r = requests.get(f"{API_BASE}/timeline/corridors", params={"hours": 24}, timeout=60)
    r.raise_for_status()
    return r.json()


try:
    data = fetch_timeline()
except requests.RequestException as e:
    st.error(f"Couldn't reach the API at {API_BASE}: {e}")
    st.stop()

hours = data["hours"]
st.session_state.setdefault("tl_hour", 8)
st.session_state.setdefault("tl_play", False)


def states_at(hour):
    """Flatten the timeline into corridor-state dicts for the given hour, in the
    same shape the map and status rail already consume."""
    out = []
    for c in data["corridors"]:
        s = c["series"][hour]
        out.append({
            "corridor": c["corridor"], "lat": c["lat"], "lon": c["lon"],
            "impact_level": s["impact_level"], "composite_score": s["score"],
            "congestion_duration_min": s["congestion_duration_min"],
        })
    return out


# --- transport controls ---------------------------------------------------
clock_col, ctrl_col = st.columns([2, 3])
with clock_col:
    ui.timeline_clock(st.session_state["tl_hour"], "model forecast")
with ctrl_col:
    b1, b2, b3, b4 = st.columns(4)
    if b1.button("⏮ Start", use_container_width=True):
        st.session_state["tl_hour"], st.session_state["tl_play"] = 0, False
        st.rerun()
    if b2.button("◀ Prev", use_container_width=True):
        st.session_state["tl_hour"] = (st.session_state["tl_hour"] - 1) % hours
        st.session_state["tl_play"] = False
        st.rerun()
    if b3.button("▶ Play" if not st.session_state["tl_play"] else "⏸ Pause",
                 use_container_width=True, type="primary"):
        st.session_state["tl_play"] = not st.session_state["tl_play"]
        st.rerun()
    if b4.button("Next ▶", use_container_width=True):
        st.session_state["tl_hour"] = (st.session_state["tl_hour"] + 1) % hours
        st.session_state["tl_play"] = False
        st.rerun()

# Scrubber (unkeyed: tl_hour stays the single source of truth across reruns).
scrubbed = st.slider("Hour of day", 0, hours - 1, st.session_state["tl_hour"],
                     format="%d:00")
if scrubbed != st.session_state["tl_hour"]:
    st.session_state["tl_hour"] = scrubbed
    st.session_state["tl_play"] = False

hour = st.session_state["tl_hour"]
states = states_at(hour)

# --- snapshot readouts ----------------------------------------------------
high = sum(1 for s in states if s["impact_level"] == "High")
med = sum(1 for s in states if s["impact_level"] == "Medium")
peak = max(states, key=lambda s: s["composite_score"])
busiest_hour = max(range(hours),
                   key=lambda h: sum(s["composite_score"] for s in states_at(h)))
ui.readouts([
    {"label": "Hour", "value": f"{hour:02d}:00", "accent": ui.NAVY},
    {"label": "High impact", "value": high, "sub": "corridors now", "accent": ui.RED},
    {"label": "Medium impact", "value": med, "sub": "corridors now", "accent": ui.AMBER},
    {"label": "Top corridor", "value": f"{peak['composite_score']:.0f}",
     "sub": peak["corridor"], "accent": ui.signal_colour(peak["impact_level"])},
    {"label": "Citywide peak", "value": f"{busiest_hour:02d}:00",
     "sub": "busiest forecast hour", "accent": ui.NAVY},
])

# --- map + status board ---------------------------------------------------
ui.section("Network at this hour")
COLOURS = {"High": ui.RED, "Medium": ui.AMBER, "Low": ui.GREEN}
m = folium.Map(location=[12.97, 77.59], zoom_start=12, tiles="cartodbpositron")
for s in states:
    colour = COLOURS.get(s["impact_level"], "gray")
    folium.CircleMarker(
        location=[s["lat"], s["lon"]],
        radius=6 + s["composite_score"] / 8,
        color=colour, weight=2, fill=True, fill_color=colour, fill_opacity=0.8,
        popup=folium.Popup(
            f"<b>{s['corridor']}</b><br>{hour:02d}:00<br>"
            f"Forecast risk: {s['composite_score']:.0f}/100<br>"
            f"Impact: {s['impact_level']}", max_width=200),
    ).add_to(m)
# key includes the hour so folium actually redraws as the playhead sweeps
st_folium(m, height=440, use_container_width=True, key=f"tl_map_{hour}")

ui.section("Corridor status board")
st.caption("Predicted impact at " + f"{hour:02d}:00 · ranked by forecast risk")
ui.corridor_rail(states, show_speed=False)

# --- drive the playhead ---------------------------------------------------
if st.session_state["tl_play"]:
    time.sleep(PLAY_SPEED_S)
    st.session_state["tl_hour"] = (hour + 1) % hours
    st.rerun()
