"""Page 3: Resource Deployment -- the shift-screen view of the latest brief."""
import folium
import streamlit as st
from streamlit_folium import st_folium

import ui

st.set_page_config(page_title="Resource Deployment", layout="wide")
ui.inject_css()

ui.header(
    "Operations · shift screen",
    "Resource Deployment",
    "Officer counts, deployment times and barricade locations for the most "
    "recently generated event brief.",
)

brief = st.session_state.get("last_brief")
if not brief:
    st.warning("No event brief yet — generate one on the Event Planner page first.")
    st.stop()

ui.pill(f"Event · {brief['event']}", ui.NAVY)

plan = brief.get("optimized_plan", brief["manpower_plan"])
high = sum(1 for c in brief["affected_corridors"] if c["impact_level"] == "High")
earliest = min((p["deploy_by"] for p in plan), default="—")
coverage = brief.get("coverage_pct", 100)
cov_accent = ui.GREEN if coverage >= 90 else ui.AMBER if coverage >= 60 else ui.RED
ui.readouts([
    {"label": "Officers", "value": f"{brief.get('officers_used', sum(p['officers'] for p in plan))}/{brief.get('officers_required', '—')}",
     "sub": "deployed / needed", "accent": ui.NAVY},
    {"label": "Coverage", "value": f"{coverage}%", "sub": "of officer need", "accent": cov_accent},
    {"label": "High-impact corridors", "value": high, "accent": ui.RED},
    {"label": "Barricade points", "value": len(brief["barricade_points"]), "accent": ui.NAVY},
    {"label": "First deploy", "value": earliest, "sub": "earliest start", "accent": ui.NAVY},
])

if coverage < 100:
    st.warning(f"Officer budget covers {coverage}% of the need — {brief.get('unmet_officers', 0)} short. The optimizer prioritizes High-impact corridors.")

ui.section("Optimized deployment schedule")
st.caption("Assigned vs required officers per corridor, sorted by deploy time.")
plan_sorted = sorted(plan, key=lambda p: p["deploy_by"])
ui.optimized_plan_table(plan_sorted)
if brief.get("tow_truck_corridors"):
    st.caption("🚛 Tow trucks pre-positioned at: " + ", ".join(brief["tow_truck_corridors"]))

ui.section("Barricade cordon & tow-truck staging")
tow_positions = brief.get("tow_truck_positions", [])
if brief["barricade_points"] or tow_positions:
    pts = [(b["lat"], b["lon"]) for b in brief["barricade_points"]]
    pts += [(t["lat"], t["lon"]) for t in tow_positions]
    avg_lat = sum(p[0] for p in pts) / len(pts)
    avg_lon = sum(p[1] for p in pts) / len(pts)
    m = folium.Map(location=[avg_lat, avg_lon], zoom_start=13, tiles="cartodbpositron")
    for bp in brief["barricade_points"]:
        ui.barricade_marker(folium, bp["lat"], bp["lon"], bp["priority"],
                            popup=bp.get("rationale", bp["priority"])).add_to(m)
    for t in tow_positions:
        ui.tow_truck_marker(folium, t["lat"], t["lon"],
                            popup=f"Tow truck · {t['corridor']}").add_to(m)
    st_folium(m, height=420, use_container_width=True, key="resource_barricade_map")
    if tow_positions:
        st.caption("🚧 barricade cordon points · 🚛 tow-truck staging corridors")
else:
    st.caption("No barricade points or tow trucks for this event.")
