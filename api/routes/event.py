"""Day 2.5 -- /event-impact (Phase 1 planning brief) and
/event/activate-phase2 (switch a planned event into live monitoring).
"""
import hashlib
from typing import Optional

import joblib
from fastapi import APIRouter
from pydantic import BaseModel

from api.state import ACTIVE_EVENTS, EVENT_BRIEFS, compute_multiplier
from modules.barricade_planner import (
    get_barricade_points,
    get_blast_radius,
    get_route_barricade_points,
    get_route_blast_zone,
)
from modules.corridor_lookup import nodes_to_corridors
from modules.feature_builder import build_event_features, predict_label
from modules.graph_utils import get_graph
from modules.manpower_planner import get_manpower_plan

router = APIRouter()

clf = joblib.load("models/trained/impact_clf.pkl")
reg_dur = joblib.load("models/trained/duration_reg.pkl")


class EventInput(BaseModel):
    name: str
    lat: float  # static event location, or rally/road show start point
    lon: float
    attendance: int
    event_type: str  # sports / rally / festival / construction
    start_time: str  # ISO datetime
    end_lat: Optional[float] = None  # rally/road show end point -- if set,
    end_lon: Optional[float] = None  # the event is treated as a route, not a point


def _event_id(event: "EventInput") -> str:
    raw = f"{event.name}|{event.start_time}"
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


def _is_route_event(event: EventInput) -> bool:
    return event.end_lat is not None and event.end_lon is not None


@router.post("/event-impact")
def event_impact(event: EventInput):
    from datetime import datetime

    from modules.diversion_planner import get_event_diversion_routes, get_route_diversion_routes

    start_time = datetime.fromisoformat(event.start_time)
    is_route = _is_route_event(event)

    G = get_graph()
    route_length_km = None
    if is_route:
        # Marching event (rally/road show): affected zone follows the road
        # path from start -> end, scaled wider for bigger crowds, rather
        # than a circle around one point.
        buffer_m = 200 + (event.attendance / 40000) * 300
        nodes, _, route_length_km = get_route_blast_zone(
            event.lat, event.lon, event.end_lat, event.end_lon, buffer_m
        )
        radius = buffer_m / 1000
        barricades, _, _ = get_route_barricade_points(
            event.lat, event.lon, event.end_lat, event.end_lon, buffer_m
        )
        diversions = get_route_diversion_routes(event.lat, event.lon, event.end_lat, event.end_lon)
    else:
        nodes, radius = get_blast_radius(event.lat, event.lon, event.attendance)
        barricades = get_barricade_points(event.lat, event.lon, event.attendance)

    corridors = nodes_to_corridors(G, nodes)

    corridor_results = []
    for c in corridors:
        feats = build_event_features(c, event.event_type, start_time)
        impact = predict_label(clf, feats)
        dur = int(reg_dur.predict(feats)[0])
        corridor_results.append(
            {"corridor": c, "impact_level": impact, "congestion_duration_min": dur}
        )

    impact_map = {r["corridor"]: r["impact_level"] for r in corridor_results}
    manpower = get_manpower_plan(
        corridors, impact_map, event.event_type, start_time, route_length_km=route_length_km
    )
    if not is_route:
        diversions = get_event_diversion_routes(event.lat, event.lon, corridors)

    end_time = start_time.replace(hour=23, minute=59, second=59)
    eid = _event_id(event)

    brief = {
        "event_id": eid,
        "event": event.name,
        "is_route_event": is_route,
        "blast_radius_km": round(radius, 2),
        "route_length_km": route_length_km,
        "affected_corridors": corridor_results,
        "manpower_plan": manpower,
        "barricade_points": barricades,
        "diversion_routes": diversions,
        "_corridors": corridors,
        "_attendance": event.attendance,
        "_end_time": end_time.isoformat(),
    }
    EVENT_BRIEFS[eid] = brief
    return {k: v for k, v in brief.items() if not k.startswith("_")}


@router.post("/event/activate-phase2/{event_id}")
def activate_phase2(event_id: str):
    """Officer clicks 'Event Started' on the dashboard."""
    from datetime import datetime

    brief = EVENT_BRIEFS.get(event_id)
    if not brief:
        return {"status": "error", "detail": f"unknown event_id {event_id}"}

    ACTIVE_EVENTS[event_id] = {
        "corridors": brief["_corridors"],
        "multiplier": compute_multiplier(brief["_attendance"]),
        "end_time": datetime.fromisoformat(brief["_end_time"]),
        "name": brief["event"],
    }
    return {"status": "Phase 2 active", "monitoring": brief["_corridors"]}
