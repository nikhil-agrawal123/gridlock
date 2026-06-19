"""Day 4.2 -- Page 2: Event Planner (Priority -- this is the PS2 demo)."""
from datetime import datetime

import folium
import requests
import streamlit as st
from streamlit_folium import st_folium

from config import API_BASE
from modules.geocode import geocode_place

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

# Single source of truth for where the event is -- search/map-click/manual
# entry all write here, and everything downstream just reads these.
st.session_state.setdefault("ep_lat", 12.9794)
st.session_state.setdefault("ep_lon", 77.5996)
st.session_state.setdefault("ep_end_lat", 12.9716)
st.session_state.setdefault("ep_end_lon", 77.6190)

if is_route:
    st.caption("Affected zone follows the road path from start to end, not a circle around one point.")
else:
    st.caption("Type a place name, click the map, or enter coordinates directly.")

# --- Place-name search ---
search_cols = st.columns(2) if is_route else [st.container()]
with search_cols[0]:
    start_place = st.text_input("Search start place" if is_route else "Search place", placeholder="e.g. Chinnaswamy Stadium")
    if st.button("Locate start" if is_route else "Locate", key="locate_start"):
        try:
            st.session_state["ep_lat"], st.session_state["ep_lon"] = geocode_place(start_place)
            st.rerun()
        except ValueError as e:
            st.error(str(e))
if is_route:
    with search_cols[1]:
        end_place = st.text_input("Search end place", placeholder="e.g. Freedom Park")
        if st.button("Locate end", key="locate_end"):
            try:
                st.session_state["ep_end_lat"], st.session_state["ep_end_lon"] = geocode_place(end_place)
                st.rerun()
            except ValueError as e:
                st.error(str(e))

# --- Click-to-pick map ---
pick_target = "start"
if is_route:
    pick_target = st.radio("Map click sets:", ["Start point", "End point"], horizontal=True)

picker_map = folium.Map(location=[st.session_state["ep_lat"], st.session_state["ep_lon"]], zoom_start=12)
folium.Marker(
    [st.session_state["ep_lat"], st.session_state["ep_lon"]],
    tooltip="Start" if is_route else "Venue", icon=folium.Icon(color="blue"),
).add_to(picker_map)
if is_route:
    folium.Marker(
        [st.session_state["ep_end_lat"], st.session_state["ep_end_lon"]],
        tooltip="End", icon=folium.Icon(color="green"),
    ).add_to(picker_map)

map_data = st_folium(picker_map, height=350, use_container_width=True, key="picker_map")
last_clicked = map_data.get("last_clicked") if map_data else None
if last_clicked:
    click_coords = (round(last_clicked["lat"], 6), round(last_clicked["lng"], 6))
    if click_coords != st.session_state.get("ep_last_click"):
        st.session_state["ep_last_click"] = click_coords
        if pick_target == "Start point" or not is_route:
            st.session_state["ep_lat"], st.session_state["ep_lon"] = click_coords
        else:
            st.session_state["ep_end_lat"], st.session_state["ep_end_lon"] = click_coords
        st.rerun()


# --- Manual fine-tuning ---
# Controlled-component pattern: the widget reads its current value from
# session_state and writes the (possibly edited) value straight back.
# We deliberately do NOT give the number_input the same `key` as the
# session_state entry -- a widget that owns the key gets reset to the
# input's own default (0.0) whenever it's conditionally hidden (e.g.
# toggling route mode), which would clobber the stored coordinate.
def coord_input(label, state_key):
    val = st.number_input(label, value=float(st.session_state[state_key]), format="%.4f")
    st.session_state[state_key] = val
    return val


if is_route:
    rcol1, rcol2 = st.columns(2)
    with rcol1:
        st.markdown("**Start point**")
        lat = coord_input("Start latitude", "ep_lat")
        lon = coord_input("Start longitude", "ep_lon")
    with rcol2:
        st.markdown("**End point**")
        end_lat = coord_input("End latitude", "ep_end_lat")
        end_lon = coord_input("End longitude", "ep_end_lon")
else:
    lat = coord_input("Venue latitude", "ep_lat")
    lon = coord_input("Venue longitude", "ep_lon")
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
