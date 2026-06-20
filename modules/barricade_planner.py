"""Day 2.3 -- Barricade Planner (Module 2 Part A).

A barricade plan rings the venue: traffic police seal the roads that cross
into the event's closure zone (the "cordon"), so cross-town traffic is
turned away at the perimeter rather than funneled past the crowd. We find
the road-network edges that straddle the blast-radius boundary, rank the
entry points by betweenness centrality (cached from Day 1), and spread them
around the ring so barricades don't bunch on one junction.
"""
import math

import networkx as nx
import osmnx as ox

from modules.graph_utils import get_betweenness, get_graph


def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _dedupe_by_distance(G, ranked_nodes, min_sep_m):
    """Walk nodes in priority order, keeping one only if it's at least
    min_sep_m from every node already kept -- spreads barricades out."""
    kept = []
    for n in ranked_nodes:
        y, x = G.nodes[n]["y"], G.nodes[n]["x"]
        if all(_haversine_m(y, x, G.nodes[k]["y"], G.nodes[k]["x"]) >= min_sep_m for k in kept):
            kept.append(n)
    return kept


def get_blast_radius(lat, lon, attendance):
    """Radius scales with attendance: 40k people -> 4km."""
    radius_km = 1.5 + (attendance / 40000) * 2.5
    radius_m = radius_km * 1000

    G = get_graph()
    nodes = [
        n
        for n, d in G.nodes(data=True)
        if math.dist([d["y"], d["x"]], [lat, lon]) * 111000 < radius_m
    ]
    return nodes, radius_km


def get_affected_zone(lat, lon, attendance):
    """The realistic affected zone: the *intersection* of the geometric
    blast circle and the road-network propagation effect. A node counts as
    affected only if it is both within the circle AND reachable from the
    venue by road within a comparable network distance -- so congestion
    propagation respects the actual street connectivity instead of flagging
    every corridor that merely clips the circle (e.g. across a lake/railway).

    Returns (affected_nodes, radius_km).
    """
    import networkx as nx

    from modules.graph_utils import get_simple_graph

    G = get_graph()
    Gs = get_simple_graph()
    circle_nodes, radius_km = get_blast_radius(lat, lon, attendance)
    circle_set = set(circle_nodes)

    try:
        venue = ox.distance.nearest_nodes(G, lon, lat)
        reach = nx.single_source_dijkstra_path_length(
            Gs, venue, cutoff=radius_km * 1000 * 1.4, weight="length"
        )
    except Exception:
        return circle_nodes, radius_km  # fall back to the geometric circle

    affected = [n for n in circle_set if n in reach]
    return (affected or circle_nodes), radius_km


_IMPACT_W = {"High": 1.6, "Medium": 1.0, "Low": 0.6}


def _barricade_dict(G, bc, n, hi_cutoff, corridor=None, near_hotspot=False, impact=None, priority_score=None):
    b = bc.get(n, 0.0)
    bits = []
    if corridor:
        bits.append(f"on {corridor}" + (f" ({impact} impact)" if impact else ""))
    bits.append(f"betweenness {round(b, 4)}")
    if near_hotspot:
        bits.append("near historical hotspot")
    return {
        "node_id": n,
        "lat": G.nodes[n]["y"],
        "lon": G.nodes[n]["x"],
        "betweenness": round(b, 4),
        "corridor": corridor,
        "priority": "HIGH" if (priority_score if priority_score is not None else b) >= hi_cutoff else "MEDIUM",
        "rationale": "Boundary road " + ", ".join(bits),
    }


def get_cordon_barricades(lat, lon, attendance, max_points=8, min_sep_m=350,
                          corridor_risk=None, hotspots=None):
    """Barricades on the roads crossing the closure boundary -- a cordon
    ringing the venue.

    The placement is the *intersection of the cordon ring and the prediction
    model*: candidate boundary roads are ranked not by raw betweenness alone
    but by  betweenness x predicted-corridor-impact x historical-hotspot
    proximity, so barricades land where a busy entry road also sits on a
    corridor the model flags High and where incidents have historically
    clustered -- rather than on every geometrically-busy boundary road.

      corridor_risk : {corridor: 'Low'|'Medium'|'High'} from the forecast
      hotspots      : [{lat, lon, ...}] historical blackspots near the venue
    """
    G = get_graph()
    bc = get_betweenness()
    inside_nodes, _ = get_blast_radius(lat, lon, attendance)
    inside_set = set(inside_nodes)

    # Inside endpoints of boundary-crossing edges = roads entering the zone.
    cordon = set()
    for u, v in G.edges():
        iu, iv = u in inside_set, v in inside_set
        if iu != iv:
            cordon.add(u if iu else v)
    if not cordon:
        return []

    hotspots = hotspots or []

    def node_corridor(n):
        if corridor_risk is None:
            return None
        from modules.corridor_lookup import nearest_corridor

        return nearest_corridor(G.nodes[n]["y"], G.nodes[n]["x"])

    def near_hotspot(n):
        y, x = G.nodes[n]["y"], G.nodes[n]["x"]
        return any(_haversine_m(y, x, h["lat"], h["lon"]) < 800 for h in hotspots)

    meta = {}
    scored = []
    for n in cordon:
        corr = node_corridor(n)
        impact = corridor_risk.get(corr) if (corridor_risk and corr) else None
        hot = near_hotspot(n)
        score = bc.get(n, 0.0) * _IMPACT_W.get(impact, 1.0) * (1.4 if hot else 1.0)
        meta[n] = (corr, impact, hot, score)
        scored.append(n)

    ranked = sorted(scored, key=lambda n: meta[n][3], reverse=True)
    spread = _dedupe_by_distance(G, ranked, min_sep_m)[:max_points]
    if not spread:
        return []

    cutoff = meta[spread[max(0, len(spread) // 3 - 1)]][3]
    return [
        _barricade_dict(
            G, bc, n, cutoff, corridor=meta[n][0], near_hotspot=meta[n][2],
            impact=meta[n][1], priority_score=meta[n][3],
        )
        for n in spread
    ]


# Backwards-compatible alias: the old name now returns the cordon plan.
def get_barricade_points(lat, lon, attendance, top_n=8):
    return get_cordon_barricades(lat, lon, attendance, max_points=top_n)


# --- Route events (rally / road show): the affected zone follows a path
# from A to B along the road network, not a circle around one point. ---


def get_route_path(start_lat, start_lon, end_lat, end_lon):
    """Road-network shortest path the march actually walks, start -> end."""
    G = get_graph()
    start_node = ox.distance.nearest_nodes(G, start_lon, start_lat)
    end_node = ox.distance.nearest_nodes(G, end_lon, end_lat)
    return nx.shortest_path(G, start_node, end_node, weight="length")


def _path_length_km(G, path):
    return sum(G[u][v][0].get("length", 0) for u, v in zip(path[:-1], path[1:])) / 1000


def get_route_blast_zone(start_lat, start_lon, end_lat, end_lon, buffer_m=400, sample_every_m=150):
    """All nodes within buffer_m of the route path -- the corridor-shaped
    equivalent of get_blast_radius for a point event. Pre-filters by
    bounding box and checks distance against a subsampled path (not every
    path node) so this stays fast on a 155k-node graph."""
    G = get_graph()
    path = get_route_path(start_lat, start_lon, end_lat, end_lon)
    path_coords = [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in path]

    sampled = [path_coords[0]]
    acc = 0.0
    for (y1, x1), (y2, x2) in zip(path_coords[:-1], path_coords[1:]):
        acc += math.dist([y1, x1], [y2, x2]) * 111000
        if acc >= sample_every_m:
            sampled.append((y2, x2))
            acc = 0.0
    sampled.append(path_coords[-1])

    buf_deg = buffer_m / 111000
    lats = [c[0] for c in path_coords]
    lons = [c[1] for c in path_coords]
    lat_lo, lat_hi = min(lats) - buf_deg, max(lats) + buf_deg
    lon_lo, lon_hi = min(lons) - buf_deg, max(lons) + buf_deg

    nodes = set(path)
    for n, d in G.nodes(data=True):
        if n in nodes:
            continue
        y, x = d["y"], d["x"]
        if not (lat_lo <= y <= lat_hi and lon_lo <= x <= lon_hi):
            continue
        if any(math.dist([y, x], [py, px]) * 111000 < buffer_m for py, px in sampled):
            nodes.add(n)

    return list(nodes), path, round(_path_length_km(G, path), 2)


def get_route_barricade_points(start_lat, start_lon, end_lat, end_lon, buffer_m=400, spacing_km=1.2):
    """Cordon a marching route over its WHOLE length: walk the procession
    path in even slots (~spacing_km apart) and, in each slot, barricade the
    busiest cross-street near that stretch. Bucketing by position along the
    path guarantees coverage end-to-end instead of bunching at one end."""
    G = get_graph()
    bc = get_betweenness()
    zone_nodes, path, path_length_km = get_route_blast_zone(start_lat, start_lon, end_lat, end_lon, buffer_m)
    if len(path) < 3 or path_length_km <= 0:
        return [], path, path_length_km

    coords = [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in path]
    cum = [0.0]
    for (y1, x1), (y2, x2) in zip(coords[:-1], coords[1:]):
        cum.append(cum[-1] + _haversine_m(y1, x1, y2, x2))
    total = cum[-1] or 1.0

    zone = list(zone_nodes)
    n_slots = max(3, round(path_length_km / spacing_km))
    picked = []
    for i in range(n_slots):
        target = total * (i + 0.5) / n_slots  # centre of each slot along the path
        pj = min(range(len(cum)), key=lambda j: abs(cum[j] - target))
        py, px = coords[pj]
        cands = [n for n in zone if _haversine_m(py, px, G.nodes[n]["y"], G.nodes[n]["x"]) < buffer_m]
        if not cands:
            continue
        best = max(cands, key=lambda n: bc.get(n, 0.0))
        by, bx = G.nodes[best]["y"], G.nodes[best]["x"]
        if all(_haversine_m(by, bx, G.nodes[p]["y"], G.nodes[p]["x"]) >= spacing_km * 1000 * 0.5 for p in picked):
            picked.append(best)
    if not picked:
        return [], path, path_length_km

    ordered = sorted(picked, key=lambda n: bc.get(n, 0.0), reverse=True)
    hi_cutoff = bc.get(ordered[max(0, len(ordered) // 3 - 1)], 0.0)
    barricades = [_barricade_dict(G, bc, n, hi_cutoff) for n in picked]
    return barricades, path, path_length_km
