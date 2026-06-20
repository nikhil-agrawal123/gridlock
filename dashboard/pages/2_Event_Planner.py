"""Page 2: Event Planner -- generate a full deployment brief for an event."""
from datetime import date, datetime, timedelta

import folium
import requests
import streamlit as st
from streamlit_folium import st_folium

import ui
from config import API_BASE
from modules.geocode import geocode_place

st.set_page_config(page_title="Event Planner", layout="wide")
ui.inject_css()

ui.header(
    "Phase 1 · planning",
    "Event Planner",
    "Describe an upcoming event to forecast corridor impact and generate a "
    "deployment brief: manpower, barricades and diversion routes.",
)

# --- event details -------------------------------------------------------
ui.section("Event details")
col1, col2 = st.columns(2)
with col1:
    event_name = st.text_input("Event name", "IPL Match - RCB vs MI")
    event_type = st.selectbox("Type", ["sports", "rally", "festival", "construction"])
    attendance = st.slider("Expected attendance", 1000, 100000, 40000, 1000)
with col2:
    start_date = st.date_input(
        "Date", min_value=date.today(), max_value=date.today() + timedelta(days=3),
        help="Up to 3 days ahead — within the live weather forecast window.",
    )
    start_time = st.time_input("Start time")

is_route = st.checkbox(
    "Moving event (rally / road show) — affects a route, not a single venue"
)

# Single source of truth for where the event is -- search/map-click/manual
# entry all write here, and everything downstream just reads these.
st.session_state.setdefault("ep_lat", 12.9794)
st.session_state.setdefault("ep_lon", 77.5996)
st.session_state.setdefault("ep_end_lat", 12.9716)
st.session_state.setdefault("ep_end_lon", 77.6190)

# --- location ------------------------------------------------------------
ui.section("Location")
st.caption(
    "Route follows the road path from start to end."
    if is_route
    else "Type a place name, click the map, or enter coordinates directly."
)

# Place-name search
search_cols = st.columns(2) if is_route else [st.container()]
with search_cols[0]:
    start_place = st.text_input(
        "Search start place" if is_route else "Search place",
        placeholder="e.g. Chinnaswamy Stadium",
    )
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

# Click-to-pick map
pick_target = "start"
if is_route:
    pick_target = st.radio("Map click sets:", ["Start point", "End point"], horizontal=True)

picker_map = folium.Map(
    location=[st.session_state["ep_lat"], st.session_state["ep_lon"]],
    zoom_start=12, tiles="cartodbpositron",
)
folium.Marker(
    [st.session_state["ep_lat"], st.session_state["ep_lon"]],
    tooltip="Start" if is_route else "Venue", icon=folium.Icon(color="blue"),
).add_to(picker_map)
if is_route:
    folium.Marker(
        [st.session_state["ep_end_lat"], st.session_state["ep_end_lon"]],
        tooltip="End", icon=folium.Icon(color="green"),
    ).add_to(picker_map)

map_data = st_folium(picker_map, height=320, use_container_width=True, key="picker_map")
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


# Manual fine-tuning. Controlled-component pattern: read value from
# session_state and write it straight back. We deliberately do NOT give the
# number_input the same `key` as the session_state entry -- a widget that
# owns the key gets reset to the input's default (0.0) when it's
# conditionally hidden (toggling route mode), clobbering the coordinate.
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

# --- available resources (for the optimizer) ---
ui.section("Available resources")
st.caption("Leave at the max for an unconstrained plan, or cap them to see the optimizer ration scarce resources by priority.")
acol1, acol2, acol3 = st.columns(3)
with acol1:
    avail_officers = st.slider("Traffic officers", 0, 60, 60)
with acol2:
    avail_barricades = st.slider("Barricades", 0, 12, 12)
with acol3:
    avail_tow = st.slider("Tow trucks", 0, 6, 0)

st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)
if st.button("Generate deployment brief", type="primary"):
    with st.spinner("Computing blast radius and forecasting impact..."):
        payload = {
            "name": event_name, "lat": lat, "lon": lon,
            "attendance": attendance, "event_type": event_type,
            "start_time": datetime.combine(start_date, start_time).isoformat(),
            "available_officers": avail_officers,
            "available_barricades": avail_barricades,
            "available_tow_trucks": avail_tow,
        }
        if is_route:
            payload["end_lat"] = end_lat
            payload["end_lon"] = end_lon
        try:
            resp = requests.post(f"{API_BASE}/event-impact", json=payload, timeout=60)
            resp.raise_for_status()
            st.session_state["last_brief"] = resp.json()
        except requests.RequestException as e:
            st.error(f"Request failed: {e}")
            st.stop()

# --- brief ---------------------------------------------------------------
if "last_brief" in st.session_state:
    brief = st.session_state["last_brief"]
    st.markdown('<hr class="ts-rule"/>', unsafe_allow_html=True)
    ui.section("Deployment brief")

    high = sum(1 for c in brief["affected_corridors"] if c["impact_level"] == "High")
    coverage = brief.get("coverage_pct", 100)
    cov_accent = ui.GREEN if coverage >= 90 else ui.AMBER if coverage >= 60 else ui.RED
    cards = [
        {"label": "Affected corridors", "value": len(brief["affected_corridors"]), "accent": ui.NAVY},
        {"label": "High impact", "value": high, "sub": "corridors", "accent": ui.RED},
        {"label": "Officers", "value": f"{brief.get('officers_used', 0)}/{brief.get('officers_required', 0)}",
         "sub": "deployed / needed", "accent": ui.NAVY},
        {"label": "Coverage", "value": f"{coverage}%", "sub": "of officer need", "accent": cov_accent},
        {"label": "Barricades", "value": len(brief["barricade_points"]), "accent": ui.NAVY},
    ]
    if brief.get("is_route_event") and brief.get("route_length_km"):
        cards.append({"label": "Route length", "value": f"{brief['route_length_km']} km", "accent": ui.NAVY})
    elif brief.get("blast_radius_km"):
        cards.append({"label": "Blast radius", "value": f"{brief['blast_radius_km']} km", "accent": ui.NAVY})
    wx = brief.get("weather")
    if wx and wx.get("condition"):
        cards.append({"label": "Weather", "value": wx["condition"], "sub": f"×{wx['factor']}", "accent": ui.NAVY})
    ui.readouts(cards)
    if wx and not wx.get("forecast_available"):
        st.caption("⚠ Event is beyond the 3-day weather forecast window — weather assumed neutral in the prediction.")

    if st.button("Event started — activate live monitoring (Phase 2)"):
        try:
            r = requests.post(f"{API_BASE}/event/activate-phase2/{brief['event_id']}", timeout=10)
            r.raise_for_status()
            st.success(f"Phase 2 active — monitoring {len(r.json()['monitoring'])} corridors.")
        except requests.RequestException as e:
            st.error(f"Activation failed: {e}")

    ui.section("Impact forecast")
    ui.impact_forecast_table(brief["affected_corridors"])

    ui.section("Officer deployment (optimized)")
    if coverage < 100:
        st.warning(f"Officer budget covers {coverage}% of the need — {brief.get('unmet_officers', 0)} short. High-impact corridors are prioritized.")
    ui.optimized_plan_table(brief.get("optimized_plan", brief["manpower_plan"]))
    if brief.get("tow_truck_corridors"):
        st.caption("Tow trucks pre-positioned at: " + ", ".join(brief["tow_truck_corridors"]))

    ui.section("Barricade cordon")
    is_route = brief.get("is_route_event")
    st.caption("Barricades spaced along the procession route." if is_route
               else "Barricades ring the venue on the roads crossing into the closure zone.")
    center = [(lat + end_lat) / 2, (lon + end_lon) / 2] if (is_route and end_lat) else [lat, lon]
    bm = folium.Map(location=center, zoom_start=13, tiles="cartodbpositron")
    folium.Marker([lat, lon], popup=f"{event_name}",
                  icon=folium.Icon(color="blue", icon="star")).add_to(bm)
    if is_route and end_lat:
        folium.Marker([end_lat, end_lon], popup="Route end",
                      icon=folium.Icon(color="green", icon="flag")).add_to(bm)
    for bp in brief["barricade_points"]:
        ui.barricade_marker(folium, bp["lat"], bp["lon"], bp["priority"],
                            popup=bp.get("rationale", bp["priority"])).add_to(bm)
    st_folium(bm, height=420, use_container_width=True, key="barricade_map")
    st.caption("Placement = busy boundary roads ∩ predicted high-impact corridors ∩ historical incident hotspots.")

    ui.section("Diversion routes")
    st.caption("Congestion-aware alternates that steer around the closure and already-busy corridors.")
    if brief["diversion_routes"]:
        for i, r in enumerate(brief["diversion_routes"], 1):
            spill = ", ".join(r["spillover_corridors"]) or "none"
            st.markdown(
                f'<div class="ts-readout" style="--accent:{ui.NAVY};margin-bottom:12px">'
                f'<div class="ts-readout-label">Route {i} · +{r["added_minutes"]} min · +{r["added_distance_m"]} m</div>'
                f'<div class="ts-readout-sub" style="font-size:.9rem;margin-top:.35rem">'
                f'Spillover corridors: {spill}</div></div>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("No diversion routes computed (zone too small or no path found).")

    # --- emergency ambulance route ---
    em = brief.get("emergency_route")
    ui.section("Emergency ambulance route")
    if em:
        ui.readouts([
            {"label": "Hospital", "value": em["hospital"], "accent": ui.GREEN},
            {"label": "Distance", "value": f"{em['distance_km']} km", "accent": ui.NAVY},
            {"label": "Green-corridor ETA", "value": f"{em['eta_min']} min", "accent": ui.GREEN},
            {"label": "Time saved", "value": f"+{em['time_saved_min']} min", "sub": "vs naive route", "accent": ui.NAVY},
        ])
        em_center = [(lat + em["hospital_lat"]) / 2, (lon + em["hospital_lon"]) / 2]
        em_map = folium.Map(location=em_center, zoom_start=13, tiles="cartodbpositron")
        folium.Marker([em["hospital_lat"], em["hospital_lon"]], popup=em["hospital"],
                      icon=folium.Icon(color="green", icon="plus")).add_to(em_map)
        folium.Marker([lat, lon], popup="Venue", icon=folium.Icon(color="blue", icon="star")).add_to(em_map)
        if em.get("naive_coords"):
            folium.PolyLine(em["naive_coords"], color="#B0B7C3", weight=4, opacity=0.7,
                            tooltip=f"Naive route · {em['naive_eta_min']} min").add_to(em_map)
        folium.PolyLine(em["path_coords"], color=ui.GREEN, weight=6, opacity=0.9,
                        tooltip=f"Green corridor · {em['eta_min']} min").add_to(em_map)
        st_folium(em_map, height=400, use_container_width=True, key="emergency_map")
        if em["avoided_corridors"]:
            st.caption("Avoids congested corridors: " + ", ".join(em["avoided_corridors"]))
    else:
        st.caption("No emergency route could be established for this venue.")

    # --- separate historical-blockage prediction ---
    hb = brief.get("historical_blockage", {})
    ui.section("Historical blockage prediction")
    st.caption("Independent of the blast radius — where breakdowns and closures have actually happened near here at this time of day (Astram record).")
    if hb.get("corridors"):
        ui.historical_blockage_table(hb["corridors"])
    else:
        st.caption("No historical incidents on record near this venue at this hour.")
    if hb.get("hotspots"):
        st.markdown("**Incident hotspots** (HDBSCAN blackspots)")
        hm = folium.Map(location=[lat, lon], zoom_start=13, tiles="cartodbpositron")
        for h in hb["hotspots"]:
            folium.CircleMarker([h["lat"], h["lon"]], radius=6 + h["incidents"] / 6,
                                color="#8B2E2E", fill=True, fill_color="#C0392B", fill_opacity=0.7,
                                popup=f"{h['incidents']} past incidents · closure {h['closure_rate']}").add_to(hm)
        st_folium(hm, height=360, use_container_width=True, key="hotspot_map")
