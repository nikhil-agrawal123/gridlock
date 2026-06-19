"""Day 4.1 -- TrafficSense dashboard entry point. Streamlit auto-discovers
the pages/ subdirectory next to this file for sidebar navigation, so this
file is just the landing screen + an API health check.
"""
import requests
import streamlit as st

from config import API_BASE

st.set_page_config(page_title="TrafficSense", layout="wide", page_icon="\U0001F6A6")

st.sidebar.title("TrafficSense")
st.sidebar.caption("Bengaluru Traffic Intelligence")

st.title("TrafficSense")
st.caption("Event-driven congestion intelligence for Bengaluru — Gridlock 2.0, PS2")

try:
    resp = requests.get(f"{API_BASE}/health", timeout=3)
    if resp.ok:
        st.success(f"API connected ({API_BASE})")
    else:
        st.error(f"API returned HTTP {resp.status_code}")
except requests.RequestException as e:
    st.error(f"Can't reach API at {API_BASE} -- start it with `uvicorn api.main:app --port 8000`")
    st.caption(str(e))

st.markdown(
    """
Use the sidebar to navigate:

- **Live Impact Map** -- all 22 corridors, refreshed every 15 minutes
- **Event Planner** -- generate a deployment brief for an upcoming event (the PS2 demo)
- **Resource Deployment** -- manpower + barricade plan for the last generated brief
- **Diversion Routes** -- alternate routing around the last generated brief's barricades
"""
)
