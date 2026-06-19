"""Day 4.2 -- Page 2: Event Planner (Priority -- this is the PS2 demo)."""
from datetime import datetime

import folium
import requests
import streamlit as st
from streamlit_folium import st_folium

from config import API_BASE

st.set_page_config(page_title="Event Planner", layout="wide")
st.title("Event Planner -- Phase 1")
st.caption("Enter an upcoming event to generate a full deployment brief")

col1, col2 = st.columns(2)
with col1:
    event_name = st.text_input("Event name", "IPL Match - RCB vs MI")
    event_type = st.selectbox("Type", ["sports", "rally", "festival", "construction"])
    attendance = st.slider("Expected attendance", 1000, 100000, 40000, 1000)
with col2:
    start_date = st.date_input("Date")
    start_time = st.time_input("Start time")

is_route = st.checkbox(
    "Moving event (rally / road show) -- affects a route, not a single venue"
)

if is_route:
    st.caption("Affected zone follows the road path from start to end, not a circle around one point.")
    rcol1, rcol2 = st.columns(2)
    with rcol1:
        st.markdown("**Start point**")
        lat = st.number_input("Start latitude", value=12.9750, format="%.4f")
        lon = st.number_input("Start longitude", value=77.6050, format="%.4f")
    with rcol2:
        st.markdown("**End point**")
        end_lat = st.number_input("End latitude", value=12.9716, format="%.4f")
        end_lon = st.number_input("End longitude", value=77.6190, format="%.4f")
else:
    lat = st.number_input("Venue latitude", value=12.9794, format="%.4f")
    lon = st.number_input("Venue longitude", value=77.5996, format="%.4f")
    end_lat = end_lon = None

if st.button("Generate deployment brief", type="primary"):
    with st.spinner("Computing blast radius and forecasting impact..."):
        payload = {
            "name": event_name, "lat": lat, "lon": lon,
            "attendance": attendance, "event_type": event_type,
            "start_time": datetime.combine(start_date, start_time).isoformat(),
        }
        if is_route:
            payload["end_lat"] = end_lat
            payload["end_lon"] = end_lon
        try:
            resp = requests.post(f"{API_BASE}/event-impact", json=payload, timeout=60)
            resp.raise_for_status()
            brief = resp.json()
        except requests.RequestException as e:
            st.error(f"Request failed: {e}")
            st.stop()

    st.session_state["last_brief"] = brief

if "last_brief" in st.session_state:
    brief = st.session_state["last_brief"]
    if brief.get("is_route_event"):
        st.success(
            f"Brief ready · {len(brief['affected_corridors'])} corridors · "
            f"{brief['route_length_km']} km route"
        )
    else:
        st.success(f"Brief ready · {len(brief['affected_corridors'])} corridors")

    if st.button("Event Started -- activate live monitoring (Phase 2)"):
        try:
            r = requests.post(f"{API_BASE}/event/activate-phase2/{brief['event_id']}", timeout=10)
            r.raise_for_status()
            st.info(f"Phase 2 active: monitoring {len(r.json()['monitoring'])} corridors")
        except requests.RequestException as e:
            st.error(f"Activation failed: {e}")

    st.subheader("Impact forecast")
    st.dataframe(brief["affected_corridors"], use_container_width=True)

    st.subheader("Manpower deployment")
    st.dataframe(brief["manpower_plan"], use_container_width=True)

    st.subheader("Barricade points")
    if brief.get("is_route_event"):
        map_center = [(lat + end_lat) / 2, (lon + end_lon) / 2]
    else:
        map_center = [lat, lon]
    m = folium.Map(location=map_center, zoom_start=14)
    folium.Marker([lat, lon], popup=f"{event_name} (start)", icon=folium.Icon(color="blue", icon="star")).add_to(m)
    if brief.get("is_route_event"):
        folium.Marker([end_lat, end_lon], popup=f"{event_name} (end)", icon=folium.Icon(color="green", icon="flag")).add_to(m)
    for bp in brief["barricade_points"]:
        folium.Marker(
            [bp["lat"], bp["lon"]],
            popup=f"Priority: {bp['priority']} (betweenness {bp['betweenness']})",
            icon=folium.Icon(color="red", icon="ban"),
        ).add_to(m)
    st_folium(m, height=400, use_container_width=True, key="barricade_map")

    st.subheader("Diversion routes")
    if brief["diversion_routes"]:
        for r in brief["diversion_routes"]:
            st.info(
                f"via {r['via']}  ·  +{r['added_minutes']} min  ·  "
                f"Spillover: {', '.join(r['spillover_corridors']) or 'none'}"
            )
    else:
        st.caption("No diversion routes computed for this event (blast radius too small or no path found).")
