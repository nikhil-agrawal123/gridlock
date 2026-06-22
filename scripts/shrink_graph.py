"""Offline: shrink the full Bengaluru drive graph into a memory-light arterial
graph the API can hold inside Render's 512 MB.

The full graph is 155k nodes / 394k edges (~144 MB graphml) and, loaded into an
osmnx MultiDiGraph -- twice, once as get_graph() and once as the get_simple_graph()
copy -- it OOMs the free tier. But the runtime routing / barricade / BPR code only
ever reads node {x, y} and edge {length, highway, lanes}; the heavy `geometry`
(shapely polylines), names, osmid etc. are dead weight. So we:

  1. keep only major road classes (motorway..tertiary + unclassified + _link ramps)
     -- residential/service streets are the bulk of the node count and aren't
     needed for corridor-level diversion routing;
  2. take the largest weakly-connected component so routing stays connected;
  3. strip every node/edge attribute except the few the app actually uses;
  4. recompute betweenness on the pruned graph (it's keyed by node id, and the
     ranking should reflect the surviving network).

Run locally where RAM is plentiful (needs the full graphml + osmnx):

    python scripts/shrink_graph.py                 # writes *.min.* for verification
    python scripts/shrink_graph.py --in-place       # overwrite the canonical files

The original 144 MB graphml is recoverable from Git LFS history (git checkout).
"""
import argparse
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import networkx as nx
import osmnx as ox

SRC_GRAPH = "data/bengaluru_graph.graphml"
SRC_BC = "data/betweenness.pkl"

KEEP_CLASSES = {
    "motorway", "motorway_link", "trunk", "trunk_link",
    "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link", "unclassified",
}
KEEP_NODE_ATTRS = ("x", "y")
KEEP_EDGE_ATTRS = ("length", "highway", "lanes")
BC_K = 500  # same sampling as the Day-1 build


def _hw(data):
    hw = data.get("highway", "")
    return hw[0] if isinstance(hw, (list, tuple)) and hw else hw


def _simple_digraph(H):
    """Collapse the MultiDiGraph to a simple DiGraph keeping the shortest edge --
    same shape as graph_utils.get_simple_graph, used for betweenness here."""
    S = nx.DiGraph()
    S.add_nodes_from(H.nodes(data=True))
    for u, v, d in H.edges(data=True):
        length = float(d.get("length", 1.0))
        if S.has_edge(u, v):
            if length < S[u][v]["length"]:
                S[u][v]["length"] = length
        else:
            S.add_edge(u, v, length=length)
    return S


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-place", action="store_true",
                    help="overwrite the canonical data/ files instead of writing *.min.*")
    args = ap.parse_args()

    out_graph = SRC_GRAPH if args.in_place else SRC_GRAPH.replace(".graphml", ".min.graphml")
    out_bc = SRC_BC if args.in_place else SRC_BC.replace(".pkl", ".min.pkl")

    print(f"loading {SRC_GRAPH} ...")
    G = ox.load_graphml(SRC_GRAPH)
    print(f"  full:        {G.number_of_nodes():>7,} nodes  {G.number_of_edges():>7,} edges")

    keep_edges = [(u, v, k) for u, v, k, d in G.edges(keys=True, data=True)
                  if _hw(d) in KEEP_CLASSES]
    H = G.edge_subgraph(keep_edges).copy()
    print(f"  major-class: {H.number_of_nodes():>7,} nodes  {H.number_of_edges():>7,} edges")

    wcc = max(nx.weakly_connected_components(H), key=len)
    H = H.subgraph(wcc).copy()
    print(f"  largest WCC: {H.number_of_nodes():>7,} nodes  {H.number_of_edges():>7,} edges")

    for _, d in H.nodes(data=True):
        for key in [k for k in d if k not in KEEP_NODE_ATTRS]:
            del d[key]
    for _, _, d in H.edges(data=True):
        for key in [k for k in d if k not in KEEP_EDGE_ATTRS]:
            del d[key]
    H.graph = {"crs": G.graph.get("crs", "epsg:4326"), "simplified": True}

    ox.save_graphml(H, out_graph)
    print(f"saved {out_graph}  ({os.path.getsize(out_graph)/1e6:.1f} MB, "
          f"was {os.path.getsize(SRC_GRAPH)/1e6:.0f} MB)")

    print(f"recomputing betweenness (k={BC_K}) ...")
    bc = nx.betweenness_centrality(_simple_digraph(H), k=min(BC_K, H.number_of_nodes()),
                                   weight="length", seed=42)
    with open(out_bc, "wb") as f:
        pickle.dump(bc, f)
    print(f"saved {out_bc}  ({os.path.getsize(out_bc)/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
