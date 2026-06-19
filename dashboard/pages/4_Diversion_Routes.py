"""Day 4 -- Page 4: Diversion Routes. Draws the alternate-route polylines
for the last generated event brief."""
import folium
import streamlit as st
from streamlit_folium import st_folium

ROUTE_COLOURS = ["blue", "purple", "darkgreen"]

st.set_page_config(page_title="Diversion Routes", layout="wide")
st.title("Diversion Routes")
st.caption("Alternate routing around the barricaded event zone")

brief = st.session_state.get("last_brief")
if not brief:
    st.warning("No event brief yet -- generate one on the Event Planner page first.")
    st.stop()

routes = brief["diversion_routes"]
if not routes:
    st.info("No diversion routes computed for this event.")
    st.stop()

all_coords = [c for r in routes for c in r["path_coords"]]
avg_lat = sum(c[0] for c in all_coords) / len(all_coords)
avg_lon = sum(c[1] for c in all_coords) / len(all_coords)

m = folium.Map(location=[avg_lat, avg_lon], zoom_start=14)
for bp in brief["barricade_points"]:
    folium.Marker(
        [bp["lat"], bp["lon"]], popup="Barricade",
        icon=folium.Icon(color="red", icon="ban"),
    ).add_to(m)

for i, r in enumerate(routes):
    colour = ROUTE_COLOURS[i % len(ROUTE_COLOURS)]
    folium.PolyLine(
        r["path_coords"], color=colour, weight=5, opacity=0.8,
        tooltip=f"Route {i+1}: +{r['added_minutes']} min via {r['via']}",
    ).add_to(m)
    folium.CircleMarker(r["path_coords"][0], radius=6, color=colour, fill=True, popup="Origin").add_to(m)
    folium.CircleMarker(r["path_coords"][-1], radius=6, color=colour, fill=True, popup="Destination").add_to(m)

st_folium(m, height=520, use_container_width=True, key="diversion_map")

st.subheader("Route detail")
for i, r in enumerate(routes):
    st.markdown(
        f"**Route {i+1}** ({ROUTE_COLOURS[i % len(ROUTE_COLOURS)]}) -- "
        f"+{r['added_minutes']} min, +{r['added_distance_m']} m  \n"
        f"Spillover corridors: {', '.join(r['spillover_corridors']) or 'none'}"
    )
