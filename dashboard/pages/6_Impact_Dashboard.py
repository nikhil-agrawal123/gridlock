"""Page 6: Impact Dashboard -- what the deployments actually buy the city,
in hours, litres, rupees and CO2. System-wide totals from the feedback log,
plus the projected savings of the most recent event brief."""
import requests
import streamlit as st

import ui
from config import API_BASE

st.set_page_config(page_title="Impact Dashboard", layout="wide")
ui.inject_css()

ui.header(
    "Outcomes",
    "Impact Dashboard",
    "Every diversion, deployment and early detection removes delay from the "
    "network. Here is that delay converted into the currencies a city budgets "
    "in — time, fuel, money and carbon.",
)


def _inr(n):
    """Compact Indian-style money label: ₹1.2 Cr / ₹3.4 L / ₹5,600."""
    n = float(n)
    if n >= 1e7:
        return f"₹{n/1e7:.2f} Cr"
    if n >= 1e5:
        return f"₹{n/1e5:.2f} L"
    return f"₹{n:,.0f}"


@st.cache_data(ttl=15)
def fetch_system_kpis():
    r = requests.get(f"{API_BASE}/kpis/system")
    r.raise_for_status()
    return r.json()


try:
    k = fetch_system_kpis()
except requests.RequestException as e:
    st.error(f"Couldn't reach the API at {API_BASE}: {e}")
    st.stop()

# --- system-wide headline -------------------------------------------------
ui.section("Network savings to date")
if k["incidents_managed"] == 0:
    st.info(
        "No resolved incidents logged yet. As incidents open and clear "
        "(Live Impact Map → Mark resolved, or the 15-minute poll), their "
        "savings accumulate here."
    )
else:
    ui.kpi_headline(
        _inr(k["money_saved_inr"]), "saved",
        "Estimated cost of delay avoided",
        f'Across {k["incidents_managed"]} managed incidents · '
        f'{k["avg_clearance_min"]:.0f} min average clearance',
        accent=ui.NAVY,
    )
    ui.kpi_hero([
        {"label": "Time saved", "value": f'{k["time_saved_hours"]:,.0f}', "unit": "veh-hrs",
         "caption": "delay removed from the network"},
        {"label": "Fuel saved", "value": f'{k["fuel_saved_litres"]:,.0f}', "unit": "L",
         "caption": "not burned idling in jams"},
        {"label": "CO₂ avoided", "value": f'{k["co2_avoided_kg"]/1000:,.1f}', "unit": "t",
         "caption": "tailpipe emissions prevented"},
        {"label": "Incidents managed", "value": f'{k["incidents_managed"]:,}',
         "caption": "resolved & fed back to the model"},
    ])

# --- this event's projected savings --------------------------------------
brief = st.session_state.get("last_brief")
if brief and brief.get("kpis"):
    ek = brief["kpis"]
    st.markdown('<hr class="ts-rule"/>', unsafe_allow_html=True)
    ui.section("Projected savings · latest event brief")
    ui.pill(f"Event · {brief['event']}", ui.NAVY)
    ui.kpi_hero([
        {"label": "Time saved", "value": f'{ek["time_saved_hours"]:,.0f}', "unit": "veh-hrs"},
        {"label": "Fuel saved", "value": f'{ek["fuel_saved_litres"]:,.0f}', "unit": "L"},
        {"label": "Money saved", "value": _inr(ek["money_saved_inr"])},
        {"label": "CO₂ avoided", "value": f'{ek["co2_avoided_kg"]:,.0f}', "unit": "kg"},
        {"label": "Vehicles affected", "value": f'{ek["vehicles_affected"]:,}'},
    ])
    ui.section("Where the savings come from")
    st.caption("The deployment's benefit, attributed across its three levers.")
    for s in ek["sources"]:
        if s["hours"] > 0:
            ui.why_card(
                s["source"], [s["detail"]],
                tag=f'{s["hours"]:.0f} veh-hrs', accent=ui.NAVY,
            )

# --- assumptions (show the working) --------------------------------------
st.markdown('<hr class="ts-rule"/>', unsafe_allow_html=True)
with st.expander("How these numbers are estimated"):
    st.caption(
        "These are model-based estimates, not metered measurements — there is "
        "no parallel run without a deployment to measure against. Each figure "
        "derives from the forecasts plus the published rules of thumb below. "
        "Adjusting any constant scales the result transparently."
    )
    a = k["assumptions"]
    st.dataframe(
        [{"Assumption": key.replace("_", " ").capitalize(), "Value": val}
         for key, val in a.items()],
        use_container_width=True, hide_index=True,
    )
