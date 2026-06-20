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
    route that happens to cross many short corridors).

    Each row carries a `rationale` explaining how its officer count was
    derived: base x impact-multiplier + bonuses.
    """
    route_officers_total = round(route_length_km / 2) if route_length_km else 0
    plan = []
    for i, corridor in enumerate(corridors):
        base = CORRIDOR_BASE.get(corridor, 1)
        level = impact_map.get(corridor, "Medium")
        mult = MULT[level]
        event_bonus = BONUS.get(event_type, 0) if event_type else 0
        route_bonus = 1 if i < route_officers_total else 0
        bonus = event_bonus + route_bonus
        count = max(1, round(base * mult + bonus))
        offset = DEPLOY_OFFSET_HOURS[level]
        deploy = (
            (start_time - timedelta(hours=offset)).strftime("%H:%M")
            if start_time
            else "ASAP"
        )

        parts = [f"base {base} (corridor priority) x {level} impact ({mult:g}x)"]
        if event_bonus:
            parts.append(f"+{event_bonus} {event_type} bonus")
        if route_bonus:
            parts.append("+1 along-route")
        rationale = " ".join(parts) + f" -> {count} officer" + ("s" if count != 1 else "")

        plan.append(
            {
                "corridor": corridor,
                "officers": count,
                "impact_level": level,
                "deploy_by": deploy,
                "base": base,
                "multiplier": mult,
                "bonus": bonus,
                "rationale": rationale,
                "deploy_reason": f"{offset:g}h before start for {level} impact",
            }
        )
    return plan
