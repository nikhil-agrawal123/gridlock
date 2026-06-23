"""Offline: strip dead weight from the full Bengaluru drive graph.

The full graph is 155k nodes / 394k edges (~150 MB graphml). The runtime
routing / barricade / BPR code only ever reads node {x, y} and edge {length,
highway, lanes}; the heavy `geometry` (shapely polylines), names, osmid etc.
are dead weight, so stripping them alone shrinks the file ~150MB -> ~80MB.

An earlier version of this script also dropped residential/service roads
(major-class-only filter) to fit Render's 512 MB free tier. That broke real
diversion routing: residential streets are 327k of the 394k edges and are
often the *only* local detour around a closed arterial segment, so route-event
diversions silently returned zero routes once they were gone. Now that the
backend runs on Hugging Face Spaces (~16 GB RAM), there's no reason to drop
them -- keep the full road network, only strip attributes:

  1. take the largest weakly-connected component so routing stays connected;
  2. strip every node/edge attribute except the few the app actually uses;
  3. recompute betweenness on the (still full) graph.

Run locally where RAM is plentiful (needs the full graphml + osmnx):

    python scripts/shrink_graph.py                 # writes *.min.* for verification
    python scripts/shrink_graph.py --in-place       # overwrite the canonical files

The pre-strip graphml is recoverable from Git LFS history (git checkout).
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

KEEP_NODE_ATTRS = ("x", "y")
KEEP_EDGE_ATTRS = ("length", "highway", "lanes")
BC_K = 500  # same sampling as the Day-1 build


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

    wcc = max(nx.weakly_connected_components(G), key=len)
    H = G.subgraph(wcc).copy()
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
