"""Day 2.4 -- Manpower Planner (Module 2 Part B).

Officer count per corridor = base headcount (set from the Day 1 historical
risk leaderboard) x impact-level multiplier + event-type bonus. Deploy time
is offset before the event start, scaled by how severe the impact is.
"""
from datetime import timedelta

from modules.corridor_lookup import CORRIDOR_BASE

MULT = {"Low": 0.5, "Medium": 1.0, "High": 1.5}
BONUS = {"rally": 2, "festival": 2, "sports": 1, "construction": 0}
DEPLOY_OFFSET_HOURS = {"High": 2, "Medium": 1, "Low": 0.5}


def get_manpower_plan(corridors, impact_map, event_type=None, start_time=None, route_length_km=None):
    """route_length_km is set for marching events (rally/road show): one
    extra officer per ~2km of procession, spread across the corridors the
    route passes through (not added per-corridor, which would overcount a
    route that happens to cross many short corridors)."""
    route_officers_total = round(route_length_km / 2) if route_length_km else 0
    plan = []
    for i, corridor in enumerate(corridors):
        base = CORRIDOR_BASE.get(corridor, 1)
        level = impact_map.get(corridor, "Medium")
        bonus = (BONUS.get(event_type, 0) if event_type else 0) + (1 if i < route_officers_total else 0)
        count = max(1, round(base * MULT[level] + bonus))
        offset = DEPLOY_OFFSET_HOURS[level]
        deploy = (
            (start_time - timedelta(hours=offset)).strftime("%H:%M")
            if start_time
            else "ASAP"
        )
        plan.append(
            {
                "corridor": corridor,
                "officers": count,
                "impact_level": level,
                "deploy_by": deploy,
            }
        )
    return plan
