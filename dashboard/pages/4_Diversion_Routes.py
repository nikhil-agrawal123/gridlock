"""Page 4: Diversion Routes -- alternate routing around the latest brief."""
import folium
import streamlit as st
from streamlit_folium import st_folium

import ui

# Folium marker colours per route (distinct from the red barricade markers).
ROUTE_COLOURS = ["blue", "purple", "darkgreen"]
ROUTE_HEX = {"blue": "#3D7DFF", "purple": "#8B5CF6", "darkgreen": "#1F7A4D"}

st.set_page_config(page_title="Diversion Routes", layout="wide")
ui.inject_css()

ui.header(
    "Operations · routing",
    "Diversion Routes",
    "Alternate routes around the barricaded event zone for the latest brief.",
)

brief = st.session_state.get("last_brief")
if not brief:
    st.warning("No event brief yet — generate one on the Event Planner page first.")
    st.stop()

routes = brief["diversion_routes"]
if not routes:
    st.info("No diversion routes were computed for this event.")
    st.stop()

ui.pill(f"Event · {brief['event']}", ui.NAVY)
ui.readouts([
    {"label": "Routes", "value": len(routes), "sub": "alternates found", "accent": ui.NAVY},
    {"label": "Barricades", "value": len(brief["barricade_points"]), "sub": "to avoid", "accent": ui.RED},
    {"label": "Min detour", "value": f"+{min(r['added_minutes'] for r in routes)} min", "accent": ui.NAVY},
])

ui.section("Route map")
all_coords = [c for r in routes for c in r["path_coords"]]
avg_lat = sum(c[0] for c in all_coords) / len(all_coords)
avg_lon = sum(c[1] for c in all_coords) / len(all_coords)

m = folium.Map(location=[avg_lat, avg_lon], zoom_start=14, tiles="cartodbpositron")
for bp in brief["barricade_points"]:
    ui.barricade_marker(folium, bp["lat"], bp["lon"], bp.get("priority", "HIGH"), popup="Barricade").add_to(m)
for i, r in enumerate(routes):
    colour = ROUTE_COLOURS[i % len(ROUTE_COLOURS)]
    folium.PolyLine(
        r["path_coords"], color=ROUTE_HEX[colour], weight=5, opacity=0.85,
        tooltip=f"Route {i+1}: +{r['added_minutes']} min via {r['via']}",
    ).add_to(m)
    folium.CircleMarker(r["path_coords"][0], radius=6, color=ROUTE_HEX[colour], fill=True, popup="Origin").add_to(m)
    folium.CircleMarker(r["path_coords"][-1], radius=6, color=ROUTE_HEX[colour], fill=True, popup="Destination").add_to(m)
st_folium(m, height=500, use_container_width=True, key="diversion_map")

ui.section("Route detail")
for i, r in enumerate(routes):
    colour = ROUTE_HEX[ROUTE_COLOURS[i % len(ROUTE_COLOURS)]]
    spill = ", ".join(r["spillover_corridors"]) or "none"
    st.markdown(
        f'<div class="ts-readout" style="--accent:{colour};margin-bottom:12px">'
        f'<div class="ts-readout-label">Route {i+1} · +{r["added_minutes"]} min · +{r["added_distance_m"]} m</div>'
        f'<div class="ts-readout-sub" style="font-size:.9rem;margin-top:.35rem">'
        f'Spillover corridors: {spill}</div></div>',
        unsafe_allow_html=True,
    )
