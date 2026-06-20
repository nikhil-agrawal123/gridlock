"""Day 3.1 -- Diversion Planner (Module 3).

Yen's k-shortest paths is already in networkx (`shortest_simple_paths`) --
no new dependency needed. Given a blocked set of nodes (the barricade
points closing an event zone) and an origin/destination, this returns up
to k alternate routes with added distance/time and which named corridors
the detour spills traffic onto.

Note: the Astram dataset has no corridor-to-edge mapping, only named
corridors per incident. So "blocked corridor" here means "blocked at the
barricade node(s)" rather than an entire named road -- consistent with the
blast-radius/barricade approximation used elsewhere in this pipeline.
"""
from itertools import islice

import networkx as nx

from modules.corridor_lookup import nodes_to_corridors
from modules.graph_utils import get_betweenness, get_graph, get_simple_graph

AVG_SPEED_KMH = 25.0


def k_shortest_paths(G, source, target, k=3):
    return list(islice(nx.shortest_simple_paths(G, source, target, weight="length"), k))


def _path_length(G, path):
    return sum(G[u][v]["length"] for u, v in zip(path[:-1], path[1:]))


def _describe_path(G, path, max_points=3):
    nodes = path[:: max(1, len(path) // max_points)]
    return " -> ".join(f"({G.nodes[n]['y']:.4f},{G.nodes[n]['x']:.4f})" for n in nodes)


def _build_route(G, path, normal_len):
    length = _path_length(G, path)
    return {
        "path_nodes": path,
        "path_coords": [[G.nodes[n]["y"], G.nodes[n]["x"]] for n in path],
        "added_distance_m": round(length - normal_len),
        "added_minutes": round((length - normal_len) / 1000 / AVG_SPEED_KMH * 60),
        "via": _describe_path(G, path),
        "spillover_corridors": nodes_to_corridors(G, path),
    }


def _diverse_paths(G, origin, dest, normal_len, k=2, weight="length"):
    """k cheap diverse detours: take the best path by `weight`, then block its
    middle span and re-route -- one Dijkstra per route, far faster than Yen's
    k-shortest when the detour spans hundreds of nodes. `weight` can be a
    congestion-aware cost so detours steer around already-busy corridors,
    while reported distance/time still use physical length."""
    H = G.copy()
    routes = []
    for _ in range(k):
        try:
            path = nx.shortest_path(H, origin, dest, weight=weight)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            break
        routes.append(_build_route(G, path, normal_len))
        mid = path[len(path) // 4: 3 * len(path) // 4]  # force next route to differ
        H.remove_nodes_from(mid)
    return routes


def get_diversion_routes(blocked_nodes, origin_node, dest_node, k=2, graph=None):
    G = graph if graph is not None else get_simple_graph()
    blocked = set(blocked_nodes)

    try:
        normal_path = nx.shortest_path(G, origin_node, dest_node, weight="length")
        normal_len = _path_length(G, normal_path)
    except nx.NetworkXNoPath:
        return []

    G_temp = G.copy()
    G_temp.remove_nodes_from(n for n in blocked if n in G_temp)

    try:
        paths = k_shortest_paths(G_temp, origin_node, dest_node, k)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []

    routes = []
    for path in paths:
        length = _path_length(G_temp, path)
        added_min = round((length - normal_len) / 1000 / AVG_SPEED_KMH * 60)
        routes.append(
            {
                "path_nodes": path,
                "path_coords": [[G_temp.nodes[n]["y"], G_temp.nodes[n]["x"]] for n in path],
                "added_distance_m": round(length - normal_len),
                "added_minutes": added_min,
                "via": _describe_path(G_temp, path),
                "spillover_corridors": nodes_to_corridors(G_temp, path),
            }
        )
    return routes


CONGESTION_FACTOR = {"High": 3.0, "Medium": 1.6, "Low": 1.1}


def get_event_diversion_routes(lat, lon, affected_corridors=None, attendance=40000,
                               k=2, impact_map=None):
    """Divert traffic around a sealed event zone. The whole blast-radius
    interior is closed, and we route between two "gateway" roads just
    outside the cordon on roughly opposite sides (highest-betweenness
    arterial approaches). With `impact_map` ({corridor: level}) the detour is
    congestion-aware: edges on already-High corridors cost more, so the
    alternate steers around them instead of merely hugging the cordon.
    `affected_corridors` is accepted for call-site compatibility."""
    import math

    from modules.barricade_planner import _haversine_m, get_blast_radius

    G = get_graph()
    bc = get_betweenness()
    inside, radius_km = get_blast_radius(lat, lon, attendance)
    if len(inside) < 10:
        return []
    inside_set = set(inside)
    radius_m = radius_km * 1000

    # Gateways: the OUTSIDE endpoints of edges crossing the closure boundary
    # (arterials just beyond the cordon), ranked by betweenness. Iterate the
    # directed edges directly -- to_undirected() copies the whole graph.
    gateways = set()
    for u, v in G.edges():
        iu, iv = u in inside_set, v in inside_set
        if iu != iv:
            gateways.add(v if iu else u)
    if len(gateways) < 2:
        return []
    ranked = sorted(gateways, key=lambda n: bc.get(n, 0.0), reverse=True)

    def bearing(n):
        d = G.nodes[n]
        return math.atan2(d["y"] - lat, d["x"] - lon)

    origin_node = ranked[0]
    ob = bearing(origin_node)
    # Among the busiest gateways, pick the one most opposite the origin.
    top_gw = ranked[: max(5, len(ranked) // 4)]
    dest_node = max(
        top_gw,
        key=lambda n: abs(((bearing(n) - ob + math.pi) % (2 * math.pi)) - math.pi),
    )
    if dest_node == origin_node:
        return []

    # Route within a local subgraph (event neighbourhood) -- the detour is
    # always local, so this keeps Yen's k-shortest fast instead of searching
    # the whole 155k-node city graph.
    Gs = get_simple_graph()
    margin_deg = (radius_m + 2500) / 111000
    local = [
        n for n, d in Gs.nodes(data=True)
        if abs(d["y"] - lat) < margin_deg and abs(d["x"] - lon) < margin_deg
    ]
    Glocal = Gs.subgraph(local).copy()
    if origin_node not in Glocal or dest_node not in Glocal:
        return []

    # Baseline = the would-be straight route through the zone.
    try:
        normal_len = _path_length(Glocal, nx.shortest_path(Glocal, origin_node, dest_node, weight="length"))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        normal_len = 0.0

    # Seal the interior, then find cheap diverse detours around it.
    Gsealed = Glocal.copy()
    Gsealed.remove_nodes_from(n for n in inside_set if n in Gsealed)

    # Congestion-aware cost: inflate edges on already-busy corridors so the
    # detour avoids them rather than just skirting the cordon.
    weight = "length"
    if impact_map:
        from modules.corridor_lookup import nearest_corridor

        nf = {}
        for n, d in Gsealed.nodes(data=True):
            nf[n] = CONGESTION_FACTOR.get(impact_map.get(nearest_corridor(d["y"], d["x"])), 1.0)
        for u, v, data in Gsealed.edges(data=True):
            data["cost"] = data["length"] * max(nf.get(u, 1.0), nf.get(v, 1.0))
        weight = "cost"

    routes = _diverse_paths(Gsealed, origin_node, dest_node, normal_len, k=k, weight=weight)

    # Drop degenerate routes and de-duplicate near-identical alternates.
    seen, out = set(), []
    for r in routes:
        if r["added_minutes"] <= 0:
            continue
        sig = (r["added_distance_m"], tuple(r["spillover_corridors"]))
        if sig in seen:
            continue
        seen.add(sig)
        out.append(r)
    return out


def get_route_diversion_routes(start_lat, start_lon, end_lat, end_lon, k=2, buffer_m=400, impact_map=None):
    """For a marching event (rally/road show), the road it's on is the
    blocked segment for the whole route. Traffic that would travel
    start->end along the march road must route around the closure. Uses a
    local graph + cheap diverse paths (congestion-aware when impact_map is
    given), like the point-event diversions."""
    from modules.barricade_planner import get_route_blast_zone

    _, path, path_length_km = get_route_blast_zone(start_lat, start_lon, end_lat, end_lon, buffer_m)
    if len(path) < 4 or path_length_km <= 0:
        return []

    origin_node, dest_node = path[0], path[-1]
    blocked_nodes = set(path[1:-1])
    if not blocked_nodes:
        return []

    Gs = get_simple_graph()
    cy = (start_lat + end_lat) / 2
    cx = (start_lon + end_lon) / 2
    margin_deg = (path_length_km * 1000 + 2500) / 111000
    local = [
        n for n, d in Gs.nodes(data=True)
        if abs(d["y"] - cy) < margin_deg and abs(d["x"] - cx) < margin_deg
    ]
    Glocal = Gs.subgraph(local).copy()
    if origin_node not in Glocal or dest_node not in Glocal:
        return []

    try:
        normal_len = _path_length(Glocal, nx.shortest_path(Glocal, origin_node, dest_node, weight="length"))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        normal_len = 0.0

    Gsealed = Glocal.copy()
    Gsealed.remove_nodes_from(n for n in blocked_nodes if n in Gsealed)

    weight = "length"
    if impact_map:
        from modules.corridor_lookup import nearest_corridor

        nf = {}
        for n, d in Gsealed.nodes(data=True):
            nf[n] = CONGESTION_FACTOR.get(impact_map.get(nearest_corridor(d["y"], d["x"])), 1.0)
        for u, v, data in Gsealed.edges(data=True):
            data["cost"] = data["length"] * max(nf.get(u, 1.0), nf.get(v, 1.0))
        weight = "cost"

    routes = _diverse_paths(Gsealed, origin_node, dest_node, normal_len, k=k, weight=weight)
    seen, out = set(), []
    for r in routes:
        if r["added_minutes"] <= 0:
            continue
        sig = (r["added_distance_m"], tuple(r["spillover_corridors"]))
        if sig not in seen:
            seen.add(sig)
            out.append(r)
    return out
