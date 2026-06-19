"""Shared, process-wide cache for the Bengaluru road graph and its
betweenness centrality. Loading the graphml is ~25s -- every module/route
that needs the graph should go through get_graph()/get_betweenness()
instead of loading it itself.
"""
import os
import pickle
from functools import lru_cache

import networkx as nx
import osmnx as ox

DATA_DIR = "data"
GRAPH_PATH = os.path.join(DATA_DIR, "bengaluru_graph.graphml")
BC_PATH = os.path.join(DATA_DIR, "betweenness.pkl")


@lru_cache(maxsize=1)
def get_graph():
    return ox.load_graphml(GRAPH_PATH)


@lru_cache(maxsize=1)
def get_simple_graph():
    """DiGraph collapsing the MultiDiGraph's parallel edges (keeps the
    shortest one) -- Yen's algorithm (shortest_simple_paths) needs a simple
    graph, and building this is too slow to redo per-request."""
    G = get_graph()
    H = nx.DiGraph()
    H.add_nodes_from(G.nodes(data=True))
    for u, v, data in G.edges(data=True):
        length = data.get("length", 1)
        if H.has_edge(u, v):
            if length < H[u][v]["length"]:
                H[u][v]["length"] = length
        else:
            H.add_edge(u, v, length=length)
    return H


@lru_cache(maxsize=1)
def get_betweenness():
    with open(BC_PATH, "rb") as f:
        return pickle.load(f)
