"""TrafficSense dashboard entry point. Streamlit auto-discovers the pages/
subdirectory next to this file for sidebar navigation, so this file is the
landing / system-status screen.
"""
import requests
import streamlit as st

import ui
from config import API_BASE

st.set_page_config(page_title="TrafficSense", layout="wide", page_icon="\U0001F6A6")
ui.inject_css()

st.sidebar.markdown("**TrafficSense**")
st.sidebar.caption("Bengaluru Traffic Intelligence")

ui.header(
    "Gridlock 2.0 · PS2",
    "TrafficSense",
    "Event-driven congestion intelligence for Bengaluru — forecast corridor "
    "impact, plan deployments, and route traffic around planned events.",
)

# --- system status -------------------------------------------------------
api_ok = False
try:
    api_ok = requests.get(f"{API_BASE}/health", timeout=3).ok
except requests.RequestException:
    api_ok = False

c1, c2 = st.columns([1, 2])
with c1:
    if api_ok:
        ui.pill("API connected", ui.GREEN)
    else:
        ui.pill("API offline", ui.RED)
with c2:
    if not api_ok:
        st.caption(
            f"Can't reach the API at {API_BASE}. Start it with "
            "`uvicorn api.main:app --port 8000`."
        )

# --- navigation guide ----------------------------------------------------
ui.section("Where to go")
cards = [
    ("Live Impact Map", "Every corridor's live risk score, refreshed from TomTom traffic flow."),
    ("Event Planner", "Generate a full deployment brief for an upcoming event."),
    ("Resource Deployment", "Officer counts, deploy times and barricade points for the latest brief."),
    ("Diversion Routes", "Alternate routing around the latest brief's closures."),
]
cols = st.columns(2)
for i, (name, desc) in enumerate(cards):
    with cols[i % 2]:
        st.markdown(
            f'<div class="ts-readout" style="--accent:{ui.NAVY};margin-bottom:14px">'
            f'<div class="ts-readout-label">{name}</div>'
            f'<div class="ts-readout-sub" style="font-size:.9rem;margin-top:.3rem">{desc}</div></div>',
            unsafe_allow_html=True,
        )
st.caption("Use the sidebar to navigate between pages.")
