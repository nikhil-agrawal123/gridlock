"""Day 4 -- Page 3: Resource Deployment. This is what traffic ops sees on
their shift screen -- the manpower + barricade plan for whichever event was
last generated on the Event Planner page.
"""
import folium
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(page_title="Resource Deployment", layout="wide")
st.title("Resource Deployment")
st.caption("Shift-screen view: officer counts, deploy times, and barricade locations")

brief = st.session_state.get("last_brief")
if not brief:
    st.warning("No event brief yet -- generate one on the Event Planner page first.")
    st.stop()

st.subheader(f"Event: {brief['event']}")

total_officers = sum(p["officers"] for p in brief["manpower_plan"])
high_impact = sum(1 for c in brief["affected_corridors"] if c["impact_level"] == "High")
col1, col2, col3 = st.columns(3)
col1.metric("Total officers needed", total_officers)
col2.metric("High-impact corridors", high_impact)
col3.metric("Barricade points", len(brief["barricade_points"]))

st.subheader("Deployment schedule")
plan_sorted = sorted(brief["manpower_plan"], key=lambda p: p["deploy_by"])
st.dataframe(plan_sorted, use_container_width=True)

st.subheader("Barricade map")
if brief["barricade_points"]:
    avg_lat = sum(b["lat"] for b in brief["barricade_points"]) / len(brief["barricade_points"])
    avg_lon = sum(b["lon"] for b in brief["barricade_points"]) / len(brief["barricade_points"])
    m = folium.Map(location=[avg_lat, avg_lon], zoom_start=14)
    for bp in brief["barricade_points"]:
        folium.Marker(
            [bp["lat"], bp["lon"]],
            popup=f"Priority: {bp['priority']}",
            icon=folium.Icon(color="red" if bp["priority"] == "HIGH" else "orange", icon="ban"),
        ).add_to(m)
    st_folium(m, height=400, use_container_width=True, key="resource_barricade_map")
else:
    st.caption("No barricade points for this event.")
