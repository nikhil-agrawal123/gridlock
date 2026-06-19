"""Day 2.3 -- Barricade Planner (Module 2 Part A).

Graph articulation points are mathematically the optimal barricade
locations within an event's blast radius: removing one disconnects the
local subgraph, maximally disrupting flow into the event zone. We rank
candidates by betweenness centrality (already cached from Day 1) so the
highest-traffic choke points surface first.
"""
import math

import networkx as nx
import osmnx as ox

from modules.graph_utils import get_betweenness, get_graph


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


def get_barricade_points(lat, lon, attendance, top_n=3):
    G = get_graph()
    bc = get_betweenness()
    nodes, _ = get_blast_radius(lat, lon, attendance)

    if len(nodes) < 3:
        return []

    subgraph = G.subgraph(nodes).to_undirected()

    # Articulation points: removing them maximally disrupts flow.
    art_pts = list(nx.articulation_points(subgraph))
    if not art_pts:
        return []

    # Rank by cached global betweenness centrality (avoids recomputing
    # centrality on a fresh subgraph per request).
    ranked = sorted(art_pts, key=lambda n: bc.get(n, 0.0), reverse=True)

    return [
        {
            "node_id": n,
            "lat": G.nodes[n]["y"],
            "lon": G.nodes[n]["x"],
            "betweenness": round(bc.get(n, 0.0), 4),
            "priority": "HIGH" if bc.get(n, 0.0) > 0.01 else "MEDIUM",
        }
        for n in ranked[:top_n]
    ]


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


def get_route_barricade_points(start_lat, start_lon, end_lat, end_lon, buffer_m=400, spacing_km=1.5):
    """Barricades spaced along the march route instead of clustered at one
    point -- roughly one choke point every `spacing_km`, so a longer route
    gets proportionally more barricades."""
    G = get_graph()
    bc = get_betweenness()
    nodes, path, path_length_km = get_route_blast_zone(start_lat, start_lon, end_lat, end_lon, buffer_m)

    if len(nodes) < 3:
        return [], path, path_length_km

    subgraph = G.subgraph(nodes).to_undirected()
    art_pts = list(nx.articulation_points(subgraph))
    if not art_pts:
        return [], path, path_length_km

    top_n = max(3, round(path_length_km / spacing_km))
    ranked = sorted(art_pts, key=lambda n: bc.get(n, 0.0), reverse=True)

    barricades = [
        {
            "node_id": n,
            "lat": G.nodes[n]["y"],
            "lon": G.nodes[n]["x"],
            "betweenness": round(bc.get(n, 0.0), 4),
            "priority": "HIGH" if bc.get(n, 0.0) > 0.01 else "MEDIUM",
        }
        for n in ranked[:top_n]
    ]
    return barricades, path, path_length_km
