"""Compound-incident simulation: model a concurrent *unplanned* incident
(truck overturn, multi-vehicle collision, breakdown, debris) striking during
a planned event, on top of an already-generated event brief.

These are transparent rules of thumb -- no metered data, same honesty stance
as modules.kpi. Three pure pieces:

  estimate_clearance()  how long the blockage takes to clear, managed (with the
                        deployment's pre-positioned tow + officer) vs unmanaged.
  cascade_impact()      forces the incident's corridor to High and bumps the
                        spillover neighbours within SPILLOVER_KM up one level.
  incident_cost()       the added delay / fuel / money / CO2 the blockage imposes
                        while it is open (a *negative* of the savings in kpi.py).

The route layer (api/routes/event.py) wires these to the diversion / emergency
re-routers, so the brief can be recomputed with the incident folded in.
"""
import math

from modules.corridor_lookup import get_corridor_centroids, nearest_corridor
from modules.kpi import (
    CO2_KG_PER_L,
    CORRIDOR_FLOW_VEH_PER_HR,
    FUEL_PRICE_INR_PER_L,
    IDLE_FUEL_L_PER_HR,
    VALUE_OF_TIME_INR_PER_HR,
)

# Base clearance time (min) for a fully-blocking incident, off-peak, before any
# closure-extent / resource adjustments. needs_tow => a tow truck materially
# changes how fast it clears.
INCIDENT_TYPES = {
    "truck_overturn": {"label": "Truck overturn / heavy vehicle", "base_min": 90, "needs_tow": True},
    "multi_collision": {"label": "Multi-vehicle collision", "base_min": 60, "needs_tow": True},
    "car_accident": {"label": "Car accident / breakdown", "base_min": 30, "needs_tow": False},
    "debris": {"label": "Debris / stalled vehicle", "base_min": 18, "needs_tow": False},
}

# How much of the carriageway is blocked -> stretches the clearance window.
LANES_BLOCKED = {"full": 1.5, "partial": 1.2, "single": 1.0}

PEAK_HOUR_FACTOR = 1.2       # responders slower + rubbernecking in peak traffic
TOW_ONSCENE_FACTOR = 0.6     # tow pre-positioned on the corridor -> heavy clears fast
TOW_DISPATCH_FACTOR = 1.15   # needs_tow but none staged -> dispatch + travel penalty
OFFICER_ONSCENE_FACTOR = 0.85  # an officer already on the corridor speeds scene mgmt

SPILLOVER_KM = 2.5           # affected corridors within this radius feel the spillover
PER_VEH_DELAY_CAP_MIN = 30.0  # cap on the avg per-vehicle queue wait we attribute

_LEVEL_UP = {"Low": "Medium", "Medium": "High", "High": "High"}

ASSUMPTIONS = {
    "incident_base_clearance_min": {k: v["base_min"] for k, v in INCIDENT_TYPES.items()},
    "lanes_blocked_factor": LANES_BLOCKED,
    "peak_hour_factor": PEAK_HOUR_FACTOR,
    "tow_on_scene_factor": TOW_ONSCENE_FACTOR,
    "tow_dispatch_factor": TOW_DISPATCH_FACTOR,
    "officer_on_scene_factor": OFFICER_ONSCENE_FACTOR,
    "spillover_radius_km": SPILLOVER_KM,
    "corridor_flow_veh_per_hr": CORRIDOR_FLOW_VEH_PER_HR,
    "per_vehicle_delay_cap_min": PER_VEH_DELAY_CAP_MIN,
}


def is_peak_hour(hour: int) -> bool:
    return 4 <= hour < 7 or 19 <= hour < 23


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def point_on_path(lat, lon, path_coords, threshold_m=180):
    """Is (lat, lon) within threshold_m of a polyline given as [[lat, lon], ...]?
    Used to tell whether the incident physically sits on the ambulance green
    corridor. Returns (on_path: bool, min_gap_m: int). Distance is measured to
    the path's vertices (graph nodes), which are dense enough in a city street
    network to approximate distance-to-segment."""
    if not path_coords:
        return False, 10 ** 9
    best_km = min(_haversine_km(lat, lon, p[0], p[1]) for p in path_coords)
    gap_m = best_km * 1000
    return gap_m <= threshold_m, round(gap_m)


def estimate_clearance(incident_type, lanes_blocked, peak_hour,
                       tow_prepositioned, officer_present):
    """Minutes to clear the blockage, both with the deployment's pre-positioned
    resources (managed) and without any (unmanaged). The gap between the two is
    the delay the deployment's *readiness* avoids. Returns a factor list so the
    dashboard can show its working."""
    spec = INCIDENT_TYPES[incident_type]
    lane_mult = LANES_BLOCKED.get(lanes_blocked, 1.2)

    base_block = spec["base_min"] * lane_mult
    factors = [
        {"factor": "Base clearance", "detail": spec["label"], "value": f'{spec["base_min"]} min'},
        {"factor": "Carriageway blocked", "detail": lanes_blocked, "value": f"x{lane_mult}"},
    ]
    if peak_hour:
        base_block *= PEAK_HOUR_FACTOR
        factors.append({"factor": "Peak-hour traffic", "detail": "slower response", "value": f"x{PEAK_HOUR_FACTOR}"})

    # Unmanaged: tow has to be dispatched (if needed), no officer on scene.
    unmanaged = base_block * (TOW_DISPATCH_FACTOR if spec["needs_tow"] else 1.0)

    # Managed: tow on scene if pre-positioned here, officer if one is allocated.
    managed = base_block
    if spec["needs_tow"]:
        if tow_prepositioned:
            managed *= TOW_ONSCENE_FACTOR
            factors.append({"factor": "Tow truck pre-positioned", "detail": "on scene", "value": f"x{TOW_ONSCENE_FACTOR}"})
        else:
            managed *= TOW_DISPATCH_FACTOR
            factors.append({"factor": "Tow truck dispatched", "detail": "travel delay", "value": f"x{TOW_DISPATCH_FACTOR}"})
    if officer_present:
        managed *= OFFICER_ONSCENE_FACTOR
        factors.append({"factor": "Officer on corridor", "detail": "scene management", "value": f"x{OFFICER_ONSCENE_FACTOR}"})

    return {
        "managed_min": round(managed),
        "unmanaged_min": round(unmanaged),
        "readiness_saving_min": max(0, round(unmanaged - managed)),
        "needs_tow": spec["needs_tow"],
        "factors": factors,
    }


def cascade_impact(incident_lat, incident_lon, affected_corridors):
    """Fold the incident into the event's corridor forecast.

    affected_corridors: the brief's ``affected_corridors`` list (each at least
    {corridor, impact_level}). Returns (incident_corridor, impact_map, changes)
    where impact_map is {corridor: level} with the incident corridor forced to
    High and every other affected corridor within SPILLOVER_KM bumped up one
    level. ``changes`` records before/after for the dashboard.
    """
    centroids = get_corridor_centroids()
    incident_corridor = nearest_corridor(incident_lat, incident_lon)

    impact_map = {c["corridor"]: c["impact_level"] for c in affected_corridors}
    changes = []

    before = impact_map.get(incident_corridor, "--")
    impact_map[incident_corridor] = "High"
    changes.append({"corridor": incident_corridor, "before": before,
                    "after": "High", "role": "incident"})

    for c in affected_corridors:
        name = c["corridor"]
        if name == incident_corridor or name not in centroids:
            continue
        clat, clon = centroids[name]
        if _haversine_km(incident_lat, incident_lon, clat, clon) <= SPILLOVER_KM:
            b = impact_map[name]
            a = _LEVEL_UP.get(b, b)
            if a != b:
                impact_map[name] = a
                changes.append({"corridor": name, "before": b, "after": a,
                                "role": "spillover"})

    return incident_corridor, impact_map, changes


def incident_cost(clearance_min, n_corridors):
    """Added delay the open blockage imposes, in the same currencies as kpi.py.

    Vehicles meeting the blockage over its open window queue an average of half
    the clearance time (uniform-arrival approximation, capped). This is a cost,
    not a saving -- it's what the incident *adds* on top of the event."""
    vehicles = CORRIDOR_FLOW_VEH_PER_HR * (clearance_min / 60.0) * max(1, n_corridors)
    per_veh_delay = min(clearance_min * 0.5, PER_VEH_DELAY_CAP_MIN)
    veh_hours = vehicles * per_veh_delay / 60.0
    fuel = veh_hours * IDLE_FUEL_L_PER_HR
    money = veh_hours * VALUE_OF_TIME_INR_PER_HR + fuel * FUEL_PRICE_INR_PER_L
    return {
        "vehicles_affected": int(vehicles),
        "added_delay_veh_hours": round(veh_hours, 1),
        "fuel_cost_litres": round(fuel, 1),
        "money_cost_inr": round(money),
        "co2_cost_kg": round(fuel * CO2_KG_PER_L, 1),
    }
