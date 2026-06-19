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
from modules.graph_utils import get_graph, get_simple_graph

AVG_SPEED_KMH = 25.0


def k_shortest_paths(G, source, target, k=3):
    return list(islice(nx.shortest_simple_paths(G, source, target, weight="length"), k))


def _path_length(G, path):
    return sum(G[u][v]["length"] for u, v in zip(path[:-1], path[1:]))


def _describe_path(G, path, max_points=3):
    nodes = path[:: max(1, len(path) // max_points)]
    return " -> ".join(f"({G.nodes[n]['y']:.4f},{G.nodes[n]['x']:.4f})" for n in nodes)


def get_diversion_routes(blocked_nodes, origin_node, dest_node, k=2):
    G = get_simple_graph()
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


def get_event_diversion_routes(lat, lon, affected_corridors, k=2):
    """Convenience wrapper for the /event-impact endpoint: approximates an
    origin/destination pair as the two graph nodes furthest apart within
    the blast radius (a stand-in for "traffic entering vs. exiting the
    event zone"), then diverts around the barricade points."""
    from modules.barricade_planner import get_barricade_points, get_blast_radius

    attendance = 40000  # blast radius already computed by caller; reuse default scale
    nodes, _ = get_blast_radius(lat, lon, attendance)
    if len(nodes) < 10:
        return []

    G = get_graph()
    barricades = get_barricade_points(lat, lon, attendance, top_n=5)
    blocked_nodes = [b["node_id"] for b in barricades]
    if not blocked_nodes:
        return []

    # Origin/destination: nodes nearest to the blast-radius boundary, on
    # roughly opposite sides of the event centre.
    import math

    def bearing(n):
        d = G.nodes[n]
        return math.atan2(d["y"] - lat, d["x"] - lon)

    sorted_nodes = sorted(nodes, key=bearing)
    origin_node = sorted_nodes[0]
    dest_node = sorted_nodes[len(sorted_nodes) // 2]
    if origin_node == dest_node:
        return []

    return get_diversion_routes(blocked_nodes, origin_node, dest_node, k=k)


def get_route_diversion_routes(start_lat, start_lon, end_lat, end_lon, k=2, buffer_m=400):
    """For a marching event (rally/road show), the road it's on is the
    blocked segment for the whole route, not just a few barricade points.
    Origin/dest are the route's own start and end nodes: traffic that
    would normally travel start->end along the march road now has to
    route around the entire closure -- the same need (emergency vehicles,
    cross-town traffic) the barricade plan is meant to keep moving."""
    from modules.barricade_planner import get_route_blast_zone

    _, path, path_length_km = get_route_blast_zone(start_lat, start_lon, end_lat, end_lon, buffer_m)
    if len(path) < 4 or path_length_km <= 0:
        return []

    # Block the interior of the march road but keep its two endpoints
    # reachable -- otherwise origin/dest themselves would be removed from
    # the graph before the search even starts.
    origin_node, dest_node = path[0], path[-1]
    blocked_nodes = path[1:-1]
    if not blocked_nodes:
        return []
    return get_diversion_routes(blocked_nodes, origin_node, dest_node, k=k)
