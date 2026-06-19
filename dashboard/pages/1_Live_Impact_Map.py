"""Day 4.3 -- Page 1: Live Impact Map."""
import folium
import requests
import streamlit as st
from streamlit_folium import st_folium

from config import API_BASE

st.set_page_config(page_title="Live Impact Map", layout="wide")
st.title("Live Impact Map")
st.caption("All corridors, refreshed every 15 minutes by the unplanned-incident pipeline")

if st.button("Refresh now"):
    st.cache_data.clear()


@st.cache_data(ttl=60)
def fetch_states():
    resp = requests.get(f"{API_BASE}/corridors/all", timeout=15)
    resp.raise_for_status()
    return resp.json()


try:
    states = fetch_states()
except requests.RequestException as e:
    st.error(f"Couldn't reach API at {API_BASE}: {e}")
    st.stop()

COLOURS = {"High": "red", "Medium": "orange", "Low": "green"}

m = folium.Map(location=[12.97, 77.59], zoom_start=12)
for corr in states:
    colour = COLOURS.get(corr["impact_level"], "gray")
    folium.CircleMarker(
        location=[corr["lat"], corr["lon"]],
        radius=10, color=colour, fill=True, fill_opacity=0.8,
        popup=folium.Popup(
            f"<b>{corr['corridor']}</b><br>"
            f"Score: {corr['composite_score']}/100<br>"
            f"Impact: {corr['impact_level']}<br>"
            f"Duration: {corr['congestion_duration_min']} min"
            + ("<br><i>Event nearby</i>" if corr["event_nearby"] else ""),
            max_width=200,
        ),
    ).add_to(m)

st_folium(m, height=520, use_container_width=True)

top3 = sorted(states, key=lambda c: -c["composite_score"])[:3]
st.subheader("Top 3 corridors by composite score")
st.dataframe(top3, use_container_width=True)

with st.expander("All corridor states"):
    st.dataframe(states, use_container_width=True)
    if states and states[0].get("tomtom_is_mock"):
        st.caption("TomTom feed is mocked (no TOMTOM_API_KEY set) -- deviations are deterministic placeholders.")
