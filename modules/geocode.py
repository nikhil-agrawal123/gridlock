"""Turns a free-text place name into (lat, lon) via OSM/Nominatim, biased
to Bengaluru so short queries like "MG Road" or "Chinnaswamy Stadium"
resolve to the right city instead of a same-named place elsewhere.
"""
import osmnx as ox

BIAS = "Bengaluru, Karnataka, India"


def geocode_place(query: str):
    """Returns (lat, lon). Raises ValueError if the place can't be found."""
    query = query.strip()
    if not query:
        raise ValueError("empty query")
    q = query if "bengaluru" in query.lower() or "bangalore" in query.lower() else f"{query}, {BIAS}"
    try:
        lat, lon = ox.geocode(q)
    except Exception as e:
        raise ValueError(f"couldn't locate '{query}': {e}") from e
    return lat, lon
