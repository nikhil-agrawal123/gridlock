"""Impact KPIs -- translate TrafficSense's interventions into the numbers a
city actually cares about: hours of delay avoided, litres of fuel not burned,
rupees saved, and CO2 kept out of the air.

These are *estimates*, not meter readings -- there is no parallel universe
where the event ran without a deployment to measure against. Every figure is
derived from published transport-economics rules of thumb plus the model's own
forecasts, and every constant below is returned in the `assumptions` block so
the dashboard can show its work. Honesty over false precision.

Two entry points:
  event_kpis(...)   projected savings for one planned-event deployment brief
  system_kpis()     cumulative savings across every incident resolved so far
                    (read from the feedback log -- the same data that retrains
                    the model)
"""
from modules.feedback_logger import _read_all, OUTCOMES_DIR, PREDICTIONS_DIR

# ── assumptions (Bengaluru-calibrated, 2026) ─────────────────────────────
PRIVATE_VEHICLE_SHARE = 0.60     # fraction of attendees arriving by private vehicle
AVG_OCCUPANCY = 3.0              # persons per private vehicle (event travel)
THROUGH_TRAFFIC_SHARE = 0.50    # of those vehicles, share that is through-traffic
                                # (can be rerouted) vs venue-bound (must arrive)

VALUE_OF_TIME_INR_PER_HR = 150.0   # blended value of one vehicle-hour
FUEL_PRICE_INR_PER_L = 102.0       # petrol, Bengaluru pump price
IDLE_FUEL_L_PER_HR = 0.9           # fuel burned crawling / idling in a jam
RUNNING_FUEL_L_PER_KM = 0.07       # mixed fleet, ~14 km/l
CO2_KG_PER_L = 2.31                # tailpipe CO2 per litre of petrol

GRIDLOCK_DELAY_MIN = 25.0        # delay a driver eats hitting an UNMANAGED
                                 # event closure (wrong-turn, backtrack, queue)
OFFICER_CLEARANCE_REDUCTION = 0.30  # share of congestion duration removed when
                                    # the corridor is actively staffed
CORRIDOR_FLOW_VEH_PER_HR = 1200  # arterial throughput, used for system KPIs
MANAGED_INCIDENT_SAVING_MIN = 8.0  # per-vehicle delay removed by early detection
                                   # + managed response on a resolved incident

ASSUMPTIONS = {
    "private_vehicle_share": PRIVATE_VEHICLE_SHARE,
    "avg_occupancy_persons_per_vehicle": AVG_OCCUPANCY,
    "value_of_time_inr_per_hour": VALUE_OF_TIME_INR_PER_HR,
    "fuel_price_inr_per_litre": FUEL_PRICE_INR_PER_L,
    "idle_fuel_litres_per_hour": IDLE_FUEL_L_PER_HR,
    "running_fuel_litres_per_km": RUNNING_FUEL_L_PER_KM,
    "co2_kg_per_litre": CO2_KG_PER_L,
    "unmanaged_gridlock_delay_min": GRIDLOCK_DELAY_MIN,
    "officer_clearance_reduction": OFFICER_CLEARANCE_REDUCTION,
}

_IMPACT_WEIGHT = {"Low": 0.4, "Medium": 1.0, "High": 1.8}


def _roll_up(time_saved_hours, extra_distance_km=0.0):
    """Turn vehicle-hours saved (and any extra detour distance driven) into
    fuel, money and CO2. Idle fuel saved is the big lever; the detour burns a
    little running fuel back, which we net out so the figures stay honest."""
    fuel_saved = time_saved_hours * IDLE_FUEL_L_PER_HR
    fuel_spent = max(0.0, extra_distance_km) * RUNNING_FUEL_L_PER_KM
    net_fuel = fuel_saved - fuel_spent
    money = time_saved_hours * VALUE_OF_TIME_INR_PER_HR + net_fuel * FUEL_PRICE_INR_PER_L
    return {
        "time_saved_hours": round(time_saved_hours, 1),
        "fuel_saved_litres": round(net_fuel, 1),
        "money_saved_inr": round(money),
        "co2_avoided_kg": round(net_fuel * CO2_KG_PER_L, 1),
    }


def event_kpis(affected_corridors, diversion_routes, emergency_route, attendance):
    """Projected savings for a deployment brief.

    Three additive sources, deliberately kept from double-counting the same
    vehicle:
      A. Reroute    -- through-traffic steered around the sealed zone avoids the
                       unmanaged-closure gridlock penalty (minus the detour cost).
      B. Clearance  -- venue-bound traffic on staffed corridors clears faster.
      C. Emergency  -- the green-corridor ambulance route's saved minutes.
    """
    vehicles_total = attendance * PRIVATE_VEHICLE_SHARE / AVG_OCCUPANCY
    v_through = vehicles_total * THROUGH_TRAFFIC_SHARE
    v_local = vehicles_total - v_through

    # ── A. reroute savings ──────────────────────────────────────────────
    if diversion_routes:
        avg_added_min = sum(r.get("added_minutes", 0) for r in diversion_routes) / len(diversion_routes)
        avg_added_km = sum(r.get("added_distance_m", 0) for r in diversion_routes) / len(diversion_routes) / 1000
    else:
        avg_added_min = GRIDLOCK_DELAY_MIN  # no managed detour -> no saving
        avg_added_km = 0.0
    per_vehicle_saving_min = max(0.0, GRIDLOCK_DELAY_MIN - avg_added_min)
    reroute_hours = v_through * per_vehicle_saving_min / 60.0
    reroute_extra_km = v_through * avg_added_km

    # ── B. faster clearance on staffed corridors ────────────────────────
    weights = {c["corridor"]: _IMPACT_WEIGHT.get(c["impact_level"], 1.0) for c in affected_corridors}
    wsum = sum(weights.values()) or 1.0
    clearance_hours = 0.0
    for c in affected_corridors:
        share = weights[c["corridor"]] / wsum
        v_corr = v_local * share
        minutes_removed = c.get("congestion_duration_min", 0) * OFFICER_CLEARANCE_REDUCTION
        clearance_hours += v_corr * minutes_removed / 60.0

    # ── C. emergency green corridor ─────────────────────────────────────
    emergency_min = (emergency_route or {}).get("time_saved_min", 0) or 0
    emergency_hours = emergency_min / 60.0

    total_hours = reroute_hours + clearance_hours + emergency_hours
    rolled = _roll_up(total_hours, reroute_extra_km)

    sources = [
        {"source": "Traffic rerouted around closure", "hours": round(reroute_hours, 1),
         "detail": f"{int(v_through):,} through-vehicles · {per_vehicle_saving_min:.0f} min saved each"},
        {"source": "Faster clearance on staffed corridors", "hours": round(clearance_hours, 1),
         "detail": f"{int(v_local):,} venue-bound vehicles · {int(OFFICER_CLEARANCE_REDUCTION*100)}% shorter jams"},
        {"source": "Emergency green corridor", "hours": round(emergency_hours, 2),
         "detail": f"ambulance reaches scene {emergency_min:.0f} min sooner"},
    ]
    return {
        "scope": "event_projection",
        "vehicles_affected": int(vehicles_total),
        **rolled,
        "sources": sources,
        "assumptions": ASSUMPTIONS,
    }


def system_kpis():
    """Cumulative, to-date savings across every resolved incident in the
    feedback log. Each managed incident removed some per-vehicle delay on the
    corridor(s) it touched, for as long as it was open."""
    preds, outs = _read_all(PREDICTIONS_DIR), _read_all(OUTCOMES_DIR)
    if preds.empty or outs.empty:
        return {"scope": "system_to_date", "incidents_managed": 0,
                "time_saved_hours": 0.0, "fuel_saved_litres": 0.0,
                "money_saved_inr": 0, "co2_avoided_kg": 0.0,
                "avg_clearance_min": 0.0, "assumptions": ASSUMPTIONS}

    merged = preds.merge(outs, on="incident_id", how="inner")
    total_hours = 0.0
    for _, r in merged.iterrows():
        # Cap the active-congestion window at 4h: a 24h "timeout" close doesn't
        # mean the corridor ran at peak flow for 24h, so don't let it dominate.
        duration_min = min(float(r.get("actual_resolution_min", 0) or 0), 240.0)
        corridor_count = max(1, int(r.get("actual_corridor_count", 1) or 1))
        vehicles = CORRIDOR_FLOW_VEH_PER_HR * (duration_min / 60.0) * corridor_count
        total_hours += vehicles * MANAGED_INCIDENT_SAVING_MIN / 60.0

    rolled = _roll_up(total_hours)
    avg_clearance = float(merged["actual_resolution_min"].mean())
    return {
        "scope": "system_to_date",
        "incidents_managed": int(len(merged)),
        **rolled,
        "avg_clearance_min": round(avg_clearance, 1),
        "assumptions": ASSUMPTIONS,
    }
