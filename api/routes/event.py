"""/event-impact (Phase 1 planning brief) and /event/activate-phase2.

For a planned event this assembles: the affected-corridor forecast (with
live-forecast weather folded in), the barricade cordon, congestion-aware
diversions, an optimized resource plan, an emergency ambulance route, and a
separate historical-blockage prediction. Point and moving (route) events
are both supported.
"""
import hashlib
from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from api.state import ACTIVE_EVENTS, EVENT_BRIEFS, compute_multiplier
from modules import model_registry as mr
from modules.barricade_planner import (
    get_affected_zone,
    get_cordon_barricades,
    get_route_barricade_points,
    get_route_blast_zone,
)
from modules.corridor_lookup import nodes_to_corridors
from modules.diversion_planner import get_event_diversion_routes, get_route_diversion_routes
from modules.emergency_router import get_emergency_route
from modules.feature_builder import build_event_features, predict_label
from modules.fusion import compute_score, score_breakdown
from modules.graph_utils import get_graph
from modules.historical_blockage import predict_blockages
from modules.manpower_planner import get_manpower_plan
from modules.resource_optimizer import optimize_allocation
from modules.weather import get_weather_factor

router = APIRouter()

_RISK_W = {"Low": 0.0, "Medium": 0.5, "High": 1.0}


class EventInput(BaseModel):
    name: str
    lat: float
    lon: float
    attendance: int
    event_type: str  # sports / rally / festival / construction
    start_time: str  # ISO datetime
    # Moving event (rally / road show): end point -> route, not a point.
    end_lat: Optional[float] = None
    end_lon: Optional[float] = None
    # Available resources for the optimizer; large defaults = unconstrained.
    available_officers: Optional[int] = 9999
    available_barricades: Optional[int] = 9999
    available_tow_trucks: Optional[int] = 0


def _event_id(event: "EventInput") -> str:
    raw = f"{event.name}|{event.start_time}"
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


def _corridor_risk(corridor, event_type, dt, event_mult, weather_factor):
    """Per-corridor forecast with weather folded into the score. A future
    event has no live TomTom reading, so the live-speed term is 0; the score
    is driven by the breakdown-risk model, event size and weather."""
    clf, reg_dur = mr.get_impact_clf(), mr.get_duration_reg()
    feats = build_event_features(corridor, event_type, dt)
    impact = predict_label(clf, feats)
    dur = int(reg_dur.predict(feats)[0])
    proba = clf.predict_proba(feats)[0]
    classes = list(clf.classes_)
    model_risk = float(sum(p * _RISK_W.get(str(c), 0.5) for p, c in zip(proba, classes)))
    score = compute_score(0.0, model_risk, event_mult=event_mult, weather=weather_factor)
    bd = score_breakdown(0.0, model_risk, event_mult, weather_factor)
    return {
        "corridor": corridor,
        "impact_level": impact,
        "congestion_duration_min": dur,
        "event_risk_score": score,
        "score_breakdown": bd["components"],
    }


@router.post("/event-impact")
def event_impact(event: EventInput):
    start_time = datetime.fromisoformat(event.start_time)
    is_route = event.end_lat is not None and event.end_lon is not None

    G = get_graph()
    event_mult = compute_multiplier(event.attendance)

    # Weather forecast at the venue for the event time (free tier ~3 days).
    days_ahead = (start_time.date() - datetime.now().date()).days
    weather = get_weather_factor(event.lat, event.lon, start_time)
    weather["forecast_available"] = days_ahead <= 3 and not weather["is_mock"]
    wx_factor = weather["factor"]

    # --- affected zone -> corridors (point vs moving event) ---
    if is_route:
        zone_nodes, path, route_len = get_route_blast_zone(
            event.lat, event.lon, event.end_lat, event.end_lon
        )
        corridors = nodes_to_corridors(G, zone_nodes)
        radius_km = None
        anchor_lat = (event.lat + event.end_lat) / 2  # route midpoint
        anchor_lon = (event.lon + event.end_lon) / 2
        hist_radius = max(1.5, route_len)
    else:
        affected_nodes, radius_km = get_affected_zone(event.lat, event.lon, event.attendance)
        corridors = nodes_to_corridors(G, affected_nodes)
        route_len = None
        anchor_lat, anchor_lon = event.lat, event.lon
        hist_radius = radius_km

    # --- per-corridor forecast (weather folded in) ---
    corridor_results = [
        _corridor_risk(c, event.event_type, start_time, event_mult, wx_factor) for c in corridors
    ]
    impact_map = {r["corridor"]: r["impact_level"] for r in corridor_results}

    # --- historical-blockage prediction (also feeds the cordon fusion) ---
    historical = predict_blockages(anchor_lat, anchor_lon, start_time, hist_radius)

    # --- barricades: cordon = ring INTERSECTED with the prediction model
    # (impact forecast) + historical hotspots, so they land on the boundary
    # roads that are both busy and predicted/known to be high-risk. ---
    if is_route:
        barricades, _, _ = get_route_barricade_points(
            event.lat, event.lon, event.end_lat, event.end_lon
        )
    else:
        barricades = get_cordon_barricades(
            event.lat, event.lon, event.attendance,
            corridor_risk=impact_map, hotspots=historical.get("hotspots"),
        )

    # --- diversions (congestion-aware) ---
    if is_route:
        diversions = get_route_diversion_routes(
            event.lat, event.lon, event.end_lat, event.end_lon, impact_map=impact_map
        )
    else:
        diversions = get_event_diversion_routes(
            event.lat, event.lon, corridors, attendance=event.attendance, impact_map=impact_map
        )

    # --- resource optimization ---
    manpower = get_manpower_plan(corridors, impact_map, event.event_type, start_time)
    optimized = optimize_allocation(
        manpower, event.available_officers, event.available_barricades,
        barricades, event.available_tow_trucks,
    )

    # --- emergency ambulance route (nearest hospital <-> venue) ---
    emergency = get_emergency_route(anchor_lat, anchor_lon, impact_map)

    end_time = start_time.replace(hour=23, minute=59, second=59)
    eid = _event_id(event)

    brief = {
        "event_id": eid,
        "event": event.name,
        "is_route_event": is_route,
        "blast_radius_km": round(radius_km, 2) if radius_km else None,
        "route_length_km": round(route_len, 2) if route_len else None,
        "affected_corridors": corridor_results,
        "manpower_plan": manpower,
        "optimized_plan": optimized["allocation"],
        "coverage_pct": optimized["coverage_pct"],
        "officers_required": optimized["officers_required"],
        "officers_used": optimized["officers_used"],
        "unmet_officers": optimized["unmet"],
        "tow_truck_corridors": optimized["tow_truck_corridors"],
        "barricade_points": optimized["barricades_used"],
        "diversion_routes": diversions,
        "emergency_route": emergency,
        "historical_blockage": historical,
        "weather": weather,
        "_corridors": corridors,
        "_attendance": event.attendance,
        "_end_time": end_time.isoformat(),
    }
    EVENT_BRIEFS[eid] = brief
    return {k: v for k, v in brief.items() if not k.startswith("_")}


@router.post("/event/activate-phase2/{event_id}")
def activate_phase2(event_id: str):
    """Officer clicks 'Event Started' on the dashboard.

    Activates live monitoring for the event's corridors AND pre-opens
    incidents on each corridor so the feedback loop starts tracking from
    event start (rather than waiting for speed deviation).
    """
    brief = EVENT_BRIEFS.get(event_id)
    if not brief:
        return {"status": "error", "detail": f"unknown event_id {event_id}"}

    from modules import incident_tracker as tracker

    ACTIVE_EVENTS[event_id] = {
        "corridors": brief["_corridors"],
        "multiplier": compute_multiplier(brief["_attendance"]),
        "end_time": datetime.fromisoformat(brief["_end_time"]),
        "name": brief["event"],
    }

    # Pre-open incidents on all affected corridors so the poll loop
    # handles resolution normally (same path as unplanned incidents).
    opened_ids = []
    for corridor in brief["_corridors"]:
        # Build a minimal prediction dict from the Phase 1 brief
        cr = next((c for c in brief.get("affected_corridors", [])
                    if c["corridor"] == corridor), {})
        prediction = {
            "impact_level": cr.get("impact_level", "Medium"),
            "duration_min": cr.get("congestion_duration_min", 60),
            "corridor_count": len(brief["_corridors"]),
            "score": cr.get("event_risk_score", 50),
            "features": {},
            "event_ctx": {"event_nearby": 1,
                          "corridors_under_pressure": len(brief["_corridors"])},
            "model_version": mr.current_version(),
        }
        iid = tracker.force_open(corridor, prediction)
        opened_ids.append({"corridor": corridor, "incident_id": iid})

    return {
        "status": "Phase 2 active",
        "monitoring": brief["_corridors"],
        "incidents_opened": opened_ids,
    }
