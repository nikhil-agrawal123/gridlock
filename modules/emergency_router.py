"""Emergency vehicle routing -- the "green corridor" for ambulances.

For a planned event we establish a guaranteed ambulance route between the
nearest major hospital and the venue, routed on a congestion-weighted graph
so it *avoids the corridors the event is predicted to choke* rather than
taking the geometrically shortest road through them. We report the time
saved versus a naive shortest-path that ignores the event congestion.

Congestion weighting inflates each edge's travel time by the predicted
impact of the corridor it sits on, so the optimiser steers around High
corridors.
"""
import math
from functools import lru_cache

import networkx as nx
import osmnx as ox

from modules.corridor_lookup import nearest_corridor
from modules.graph_utils import get_graph, get_simple_graph

BASE_KMH = 40.0  # free-flow urban arterial
CONGESTION_FACTOR = {"High": 3.0, "Medium": 1.6, "Low": 1.1}

# Major Bengaluru hospitals (approx. coordinates).
HOSPITALS = [
    {"name": "Victoria Hospital", "lat": 12.9627, "lon": 77.5745},
    {"name": "Bowring & Lady Curzon Hospital", "lat": 12.9826, "lon": 77.6056},
    {"name": "St. John's Medical College Hospital", "lat": 12.9293, "lon": 77.6219},
    {"name": "Manipal Hospital, Old Airport Road", "lat": 12.9590, "lon": 77.6490},
    {"name": "NIMHANS", "lat": 12.9430, "lon": 77.5960},
    {"name": "Fortis Hospital, Bannerghatta", "lat": 12.8915, "lon": 77.5965},
    {"name": "Sparsh Hospital, Infantry Road", "lat": 12.9870, "lon": 77.6030},
    {"name": "M S Ramaiah Memorial Hospital", "lat": 13.0290, "lon": 77.5650},
    {"name": "Sagar Hospital, Jayanagar", "lat": 12.9080, "lon": 77.5780},
    {"name": "Columbia Asia, Hebbal", "lat": 13.0480, "lon": 77.5920},
    {"name": "Vydehi Hospital, Whitefield", "lat": 12.9698, "lon": 77.7499},
    {"name": "Apollo Hospital, Bannerghatta", "lat": 12.8920, "lon": 77.5970},
]


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def nearest_hospital(lat, lon):
    return min(HOSPITALS, key=lambda h: _haversine_km(lat, lon, h["lat"], h["lon"]))


def _edge_minutes(length_m, factor):
    return length_m / 1000 / BASE_KMH * 60 * factor


def _path_metrics(G, path, node_factor):
    """(distance_km, real_minutes, corridors_passed) for a path, where real
    minutes inflate each edge by the congestion factor of its corridor."""
    dist = mins = 0.0
    corridors = set()
    for u, v in zip(path[:-1], path[1:]):
        length = G[u][v]["length"]
        factor = max(node_factor.get(u, 1.0), node_factor.get(v, 1.0))
        dist += length
        mins += _edge_minutes(length, factor)
        corridors.add(node_factor.get(("corr", u)) or node_factor.get(("corr", v)))
    return dist / 1000, mins, {c for c in corridors if c}


def get_emergency_route(venue_lat, venue_lon, impact_map,
                        blocked_latlon=None, block_radius_m=180):
    """Returns the ambulance plan, or None if no route is found.
    impact_map: {corridor: 'Low'|'Medium'|'High'} from the event forecast.

    blocked_latlon: an optional (lat, lon) physical blockage (e.g. an
    overturned truck). The nodes within block_radius_m of it are *removed*
    from the routable graph, so the green corridor is forced to go around the
    blockage rather than merely treating its corridor as congested."""
    Gfull = get_graph()
    Gs = get_simple_graph()
    hosp = nearest_hospital(venue_lat, venue_lon)

    # Local subgraph covering hospital + venue with margin.
    lat_lo, lat_hi = sorted([venue_lat, hosp["lat"]])
    lon_lo, lon_hi = sorted([venue_lon, hosp["lon"]])
    m = 0.03  # ~3 km
    local = [
        n for n, d in Gs.nodes(data=True)
        if lat_lo - m < d["y"] < lat_hi + m and lon_lo - m < d["x"] < lon_hi + m
    ]
    Glocal = Gs.subgraph(local).copy()

    try:
        origin = ox.distance.nearest_nodes(Gfull, hosp["lon"], hosp["lat"])
        dest = ox.distance.nearest_nodes(Gfull, venue_lon, venue_lat)
    except Exception:
        return None
    if origin not in Glocal or dest not in Glocal or origin == dest:
        return None

    # Physical blockage: drop the road around the incident from the graph so
    # the route must detour around it (origin/dest are never removed).
    if blocked_latlon is not None:
        blat, blon = blocked_latlon
        blocked = {
            n for n, d in Glocal.nodes(data=True)
            if _haversine_km(blat, blon, d["y"], d["x"]) * 1000 <= block_radius_m
        }
        blocked.discard(origin)
        blocked.discard(dest)
        Glocal.remove_nodes_from(blocked)
        if origin not in Glocal or dest not in Glocal:
            return None

    # Per-node congestion factor from the corridor it sits on.
    node_factor = {}
    for n, d in Glocal.nodes(data=True):
        corr = nearest_corridor(d["y"], d["x"])
        node_factor[n] = CONGESTION_FACTOR.get(impact_map.get(corr), 1.0)
        node_factor[("corr", n)] = corr

    # Congestion-weighted edge cost for the green-corridor route.
    for u, v, data in Glocal.edges(data=True):
        f = max(node_factor.get(u, 1.0), node_factor.get(v, 1.0))
        data["ew"] = data["length"] * f

    try:
        green = nx.shortest_path(Glocal, origin, dest, weight="ew")
        naive = nx.shortest_path(Glocal, origin, dest, weight="length")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None

    g_dist, g_min, g_corr = _path_metrics(Glocal, green, node_factor)
    n_dist, n_min, n_corr = _path_metrics(Glocal, naive, node_factor)

    avoided = sorted(
        c for c in n_corr - g_corr if impact_map.get(c) in ("High", "Medium")
    )

    return {
        "hospital": hosp["name"],
        "hospital_lat": hosp["lat"],
        "hospital_lon": hosp["lon"],
        "path_coords": [[Glocal.nodes[n]["y"], Glocal.nodes[n]["x"]] for n in green],
        "naive_coords": [[Glocal.nodes[n]["y"], Glocal.nodes[n]["x"]] for n in naive],
        "distance_km": round(g_dist, 1),
        "eta_min": round(g_min),
        "naive_eta_min": round(n_min),
        "time_saved_min": max(0, round(n_min - g_min)),
        "avoided_corridors": avoided,
    }
