"""Hostable network-impact model for the compound-incident feature.

The NetworkX planners (diversion_planner / emergency_router) *decide* the reroute;
this module *shows* whether it actually helps -- and whether it just shoves the jam
onto the next corridor -- using a lightweight static traffic-assignment model
(BPR volume-delay functions). It runs in-process on the road graph already loaded
by the API in ~1-3s, so it deploys anywhere the app deploys (no simulator binaries).

Three deterministic scenarios for a placed incident (same shape the SUMO prototype
produced, but instant and hostable):

  baseline      background + event demand, all roads open
  no_reroute    incident edge capacity collapses, routes frozen -> the jam piles up
  with_reroute  incident edge collapses and demand re-assigns -> drivers divert

Deltas are the deliverables:
  incident_cost      = VHT(no_reroute) - VHT(baseline)      network cost of the blockage
  value_of_guidance  = VHT(no_reroute) - VHT(with_reroute)  payoff of pushing the diversion
  corridor_shift     = delay(with_reroute) - delay(no_reroute) per corridor  ("did the jam move?")

Method: BPR  t = t0 * (1 + alpha*(V/C)^beta), capacities/free-flow speeds derived by
OSM road class (with lane counts where present), incremental loading toward user
equilibrium. Background load is seeded from each corridor's forecast impact level so
the assignment starts from the congestion the rest of the app already predicts.
"""
import math

import networkx as nx

from modules.corridor_lookup import nearest_corridor
from modules.graph_utils import get_graph

# Per-lane capacity (veh/hr) and free-flow speed (km/h) by OSM highway class.
LANE_CAP = {
    "motorway": 2200, "trunk": 2000, "primary": 1800, "secondary": 1400,
    "tertiary": 1000, "unclassified": 800, "residential": 600,
    "living_street": 300, "service": 300,
}
FREEFLOW_KMH = {
    "motorway": 80, "trunk": 60, "primary": 50, "secondary": 40,
    "tertiary": 35, "unclassified": 30, "residential": 25,
    "living_street": 15, "service": 15,
}
DEFAULT_LANES = {"motorway": 2, "trunk": 2, "primary": 2, "secondary": 2}
_DEFAULT_CAP, _DEFAULT_KMH, _DEFAULT_LANES = 800, 30.0, 1

BPR_ALPHA, BPR_BETA = 0.15, 4.0
VOC_CAP = 6.0          # clamp V/C so a single overloaded edge can't blow up BPR

# Background saturation (V/C) seeded per edge from its corridor's forecast level.
BG_SAT = {"High": 0.85, "Medium": 0.55, "Low": 0.30}
DEFAULT_SAT = 0.40

# Demand: attendance -> vehicles reuses the event_kpis assumption (0.60 travel by
# car, 3.0 occupancy); spread over an arrival window into a per-hour inflow.
CAR_SHARE, OCCUPANCY, ARRIVAL_WINDOW_HR = 0.60, 3.0, 2.0

K_ORIGINS = 10        # demand approaches the venue from this many directions
N_CHUNKS = 4          # incremental-loading steps toward equilibrium
BBOX_MARGIN_DEG = 0.03  # ~3 km padding around venue+incident for detour room

# Closed-edge capacity multiplier by how much of the carriageway is blocked.
LANES_BLOCK_FACTOR = {"full": 0.02, "partial": 0.40, "single": 0.50}

ASSUMPTIONS = {
    "model": "BPR static assignment  t = t0*(1+a*(V/C)^b)",
    "bpr_alpha": BPR_ALPHA, "bpr_beta": BPR_BETA,
    "per_lane_capacity_veh_per_hr": LANE_CAP,
    "freeflow_kmh_by_class": FREEFLOW_KMH,
    "background_saturation_by_impact": BG_SAT,
    "demand": "attendance*0.60/3.0 vehicles over a 2h arrival window",
    "assignment": f"{N_CHUNKS}-step incremental loading from {K_ORIGINS} approaches",
}


# --- edge attribute helpers -------------------------------------------------
def _hw_class(data):
    hw = data.get("highway", "")
    if isinstance(hw, (list, tuple)):
        hw = hw[0] if hw else ""
    return hw


def _lanes(data, hwclass):
    raw = data.get("lanes")
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    try:
        n = int(float(raw))
        if n >= 1:
            return n
    except (TypeError, ValueError):
        pass
    return DEFAULT_LANES.get(hwclass, _DEFAULT_LANES)


def edge_capacity(data):
    """Directed-edge capacity in veh/hr from road class x lane count."""
    hw = _hw_class(data)
    return _lanes(data, hw) * LANE_CAP.get(hw, _DEFAULT_CAP)


def edge_freeflow_hr(data):
    """Free-flow traversal time in hours."""
    hw = _hw_class(data)
    kmh = FREEFLOW_KMH.get(hw, _DEFAULT_KMH)
    return (data.get("length", 1.0) / 1000.0) / kmh


def bpr_time(t0, v, c):
    voc = min(v / c, VOC_CAP) if c > 0 else VOC_CAP
    return t0 * (1.0 + BPR_ALPHA * voc ** BPR_BETA)


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# --- local assignment graph -------------------------------------------------
def _build_local_graph(venue_lat, venue_lon, inc_lat, inc_lon):
    """A directed local subgraph around venue+incident with cap/t0/len per edge.
    Parallel edges are collapsed keeping the highest-capacity one."""
    G = get_graph()
    lat_lo = min(venue_lat, inc_lat) - BBOX_MARGIN_DEG
    lat_hi = max(venue_lat, inc_lat) + BBOX_MARGIN_DEG
    lon_lo = min(venue_lon, inc_lon) - BBOX_MARGIN_DEG
    lon_hi = max(venue_lon, inc_lon) + BBOX_MARGIN_DEG

    H = nx.DiGraph()
    for n, d in G.nodes(data=True):
        if lat_lo < d["y"] < lat_hi and lon_lo < d["x"] < lon_hi:
            H.add_node(n, y=d["y"], x=d["x"])
    for u, v, d in G.edges(data=True):
        if u not in H or v not in H:
            continue
        cap = edge_capacity(d)
        t0 = edge_freeflow_hr(d)
        if H.has_edge(u, v):
            if cap <= H[u][v]["cap"]:
                continue
        H.add_edge(u, v, cap=cap, t0=t0, length=d.get("length", 1.0))
    return H


def _nearest_node(H, lat, lon):
    return min(H.nodes, key=lambda n: _haversine_km(lat, lon, H.nodes[n]["y"], H.nodes[n]["x"]))


def _nearest_edge(H, lat, lon):
    """Edge whose midpoint is closest to (lat,lon)."""
    best, bestd = None, float("inf")
    for u, v in H.edges():
        my = (H.nodes[u]["y"] + H.nodes[v]["y"]) / 2
        mx = (H.nodes[u]["x"] + H.nodes[v]["x"]) / 2
        d = _haversine_km(lat, lon, my, mx)
        if d < bestd:
            best, bestd = (u, v), d
    return best


def _pick_origins(H, venue_node, k=K_ORIGINS):
    """k nodes ringing the venue from spread bearings -- demand approaches from
    all sides, so a blocked approach forces traffic onto the others."""
    vy, vx = H.nodes[venue_node]["y"], H.nodes[venue_node]["x"]
    sectors = {}
    for n in H.nodes:
        if n == venue_node:
            continue
        ny, nx_ = H.nodes[n]["y"], H.nodes[n]["x"]
        dist = _haversine_km(vy, vx, ny, nx_)
        bearing = math.atan2(ny - vy, nx_ - vx)
        sec = int((bearing + math.pi) / (2 * math.pi) * k) % k
        if sec not in sectors or dist > sectors[sec][1]:
            sectors[sec] = (n, dist)
    return [n for n, _ in sectors.values()]


def _background(H, impact_map):
    """Seed each edge's volume from its corridor's forecast impact level."""
    impact_map = impact_map or {}
    bg = {}
    for u, v, d in H.edges(data=True):
        my = (H.nodes[u]["y"] + H.nodes[v]["y"]) / 2
        mx = (H.nodes[u]["x"] + H.nodes[v]["x"]) / 2
        sat = BG_SAT.get(impact_map.get(nearest_corridor(my, mx)), DEFAULT_SAT)
        bg[(u, v)] = sat * d["cap"]
    return bg


# --- assignment -------------------------------------------------------------
def _times(G, V):
    return {(u, v): bpr_time(d["t0"], V[(u, v)], d["cap"]) for u, v, d in G.edges(data=True)}


def _load_path(V, path, q):
    for a, b in zip(path[:-1], path[1:]):
        V[(a, b)] += q


def assign_equilibrium(G, bg, origins, dest, q_per_origin_hr):
    """Incremental BPR loading toward user equilibrium: demand is added in chunks
    and each chunk takes the shortest path on the *current* (congested) times, so
    load spreads across alternatives. The 'informed / guided' scenario."""
    V = dict(bg)
    chunk = q_per_origin_hr / N_CHUNKS
    for _ in range(N_CHUNKS):
        nx.set_edge_attributes(G, _times(G, V), "cur_t")
        for o in origins:
            try:
                path = nx.shortest_path(G, o, dest, weight="cur_t")
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue
            _load_path(V, path, chunk)
    return V, _times(G, V)


def assign_all_or_nothing(G, bg, origins, dest, q_per_origin_hr):
    """Every origin sends all its demand down one shortest path computed at the
    uncongested (background) times -- drivers don't adapt to the load they create,
    so traffic concentrates. The 'uninformed / no-guidance' scenario."""
    V = dict(bg)
    nx.set_edge_attributes(G, _times(G, V), "cur_t")  # background times, fixed
    for o in origins:
        try:
            path = nx.shortest_path(G, o, dest, weight="cur_t")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
        _load_path(V, path, q_per_origin_hr)
    return V, _times(G, V)


def _metrics(H, V, t, edge_corr, event_trips):
    """System delay + per-corridor delay (veh-hours) for one scenario state."""
    total_delay = 0.0
    corridor_delay = {}
    for u, v, d in H.edges(data=True):
        e = (u, v)
        excess_hr = max(0.0, t[e] - d["t0"])      # delay per veh, hours
        delay_vehh = V[e] * excess_hr * ARRIVAL_WINDOW_HR
        if delay_vehh <= 0:
            continue
        total_delay += delay_vehh
        c = edge_corr.get(e)
        if c:
            corridor_delay[c] = corridor_delay.get(c, 0.0) + delay_vehh
    avg_min = (total_delay / event_trips * 60) if event_trips else 0.0
    return {
        "total_delay_veh_h": round(total_delay, 1),
        "avg_delay_min_per_trip": round(avg_min, 1),
        "corridor_delay": {k: round(val, 1) for k, val in corridor_delay.items()},
    }


def _edge_corridors(H):
    out = {}
    for u, v in H.edges():
        my = (H.nodes[u]["y"] + H.nodes[v]["y"]) / 2
        mx = (H.nodes[u]["x"] + H.nodes[v]["x"]) / 2
        out[(u, v)] = nearest_corridor(my, mx)
    return out


# --- the three-scenario comparison ------------------------------------------
def _closed_graph(H, incident_edge, lanes_blocked):
    """Apply the blockage: a full closure removes the edge; a partial/single
    closure shrinks its capacity. Returns a working copy."""
    Hc = H.copy()
    factor = LANES_BLOCK_FACTOR.get(lanes_blocked, 0.02)
    u, v = incident_edge
    if lanes_blocked == "full" or factor <= 0.05:
        Hc.remove_edge(u, v)
    else:
        Hc[u][v]["cap"] = max(1.0, Hc[u][v]["cap"] * factor)
    return Hc


def compare_incident(venue_lat, venue_lon, inc_lat, inc_lon,
                     lanes_blocked="full", attendance=40000, impact_map=None):
    """Run baseline / no_reroute / with_reroute and return the comparison the
    dashboard renders. Pure NetworkX on the already-loaded graph; ~1-3s."""
    H = _build_local_graph(venue_lat, venue_lon, inc_lat, inc_lon)
    if H.number_of_edges() < 20:
        return {"ok": False, "reason": "Too few roads near the venue/incident to model."}

    dest = _nearest_node(H, venue_lat, venue_lon)
    incident_edge = _nearest_edge(H, inc_lat, inc_lon)
    if incident_edge is None:
        return {"ok": False, "reason": "No road found at the incident location."}
    origins = [o for o in _pick_origins(H, dest) if o != dest]
    if not origins:
        return {"ok": False, "reason": "Could not place demand origins around the venue."}

    vehicles_total = attendance * CAR_SHARE / OCCUPANCY
    q_per_origin_hr = vehicles_total / ARRIVAL_WINDOW_HR / len(origins)
    event_trips = vehicles_total

    bg = _background(H, impact_map)
    edge_corr = _edge_corridors(H)

    # baseline: all roads open, equilibrium assignment
    V_base, t_base = assign_equilibrium(H, bg, origins, dest, q_per_origin_hr)
    base_m = _metrics(H, V_base, t_base, edge_corr, event_trips)

    # incident closes the road; same demand, two driver responses
    Hc = _closed_graph(H, incident_edge, lanes_blocked)
    bg_c = {e: bg[e] for e in Hc.edges()}

    # no_reroute: uninformed drivers concentrate on usual routes (all-or-nothing)
    V_no, t_no = assign_all_or_nothing(Hc, bg_c, origins, dest, q_per_origin_hr)
    no_m = _metrics(Hc, V_no, t_no, edge_corr, event_trips)

    # with_reroute: guided drivers spread around the closure (equilibrium)
    V_re, t_re = assign_equilibrium(Hc, bg_c, origins, dest, q_per_origin_hr)
    re_m = _metrics(Hc, V_re, t_re, edge_corr, event_trips)

    incident_corridor = nearest_corridor(inc_lat, inc_lon)
    shift = _corridor_shift(no_m["corridor_delay"], re_m["corridor_delay"])

    incident_cost = round(no_m["total_delay_veh_h"] - base_m["total_delay_veh_h"], 1)
    guidance_saved = round(no_m["total_delay_veh_h"] - re_m["total_delay_veh_h"], 1)

    return {
        "ok": True,
        "incident_corridor": incident_corridor,
        "lanes_blocked": lanes_blocked,
        "baseline": base_m,
        "no_reroute": no_m,
        "with_reroute": re_m,
        "incident_cost": {
            "extra_veh_hours_vs_baseline": incident_cost,
            "avg_delay_added_min": round(no_m["avg_delay_min_per_trip"]
                                         - base_m["avg_delay_min_per_trip"], 1),
        },
        "value_of_guidance": {
            "total_veh_hours_saved": guidance_saved,
            "avg_delay_saved_min": round(no_m["avg_delay_min_per_trip"]
                                         - re_m["avg_delay_min_per_trip"], 1),
            "guidance_helps": guidance_saved > 0,
        },
        "corridor_shift": shift,
        "assumptions": ASSUMPTIONS,
    }


def _corridor_shift(no_delay, re_delay, top=6):
    """Per-corridor delay change (with_reroute - no_reroute). Negative = guidance
    relieved it; positive = the diversion pushed traffic onto it."""
    rows = []
    for c in set(no_delay) | set(re_delay):
        before, after = no_delay.get(c, 0.0), re_delay.get(c, 0.0)
        rows.append({"corridor": c, "before_veh_h": round(before, 1),
                     "after_veh_h": round(after, 1), "delta_veh_h": round(after - before, 1)})
    rows.sort(key=lambda r: abs(r["delta_veh_h"]), reverse=True)
    return rows[:top]
