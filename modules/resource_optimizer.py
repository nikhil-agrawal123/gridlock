"""Resource Optimization Engine.

The manpower planner says how many officers each corridor *needs*. In the
real world supply is finite, so this distributes a fixed pool of officers
(plus barricades and tow trucks) across corridors by priority -- highest
predicted impact and busiest corridors first -- and reports how much of the
need each plan actually covers.

Priority = impact severity {Low:1, Medium:2, High:3} x corridor base weight
(from the Day-1 risk leaderboard, modules.corridor_lookup.CORRIDOR_BASE).
"""
from modules.corridor_lookup import CORRIDOR_BASE

SEVERITY = {"Low": 1, "Medium": 2, "High": 3}


def _priority(corridor, level):
    return SEVERITY.get(level, 2) * CORRIDOR_BASE.get(corridor, 1)


def optimize_allocation(required_plan, available_officers, available_barricades,
                        barricade_points, available_tow_trucks=0):
    """Distribute finite resources over the corridors in `required_plan`
    (the manpower plan: list of {corridor, officers, impact_level, deploy_by}).

    Officers: grant the full requirement if the budget covers it; otherwise
    guarantee 1 to every High-impact corridor, then hand out the remaining
    officers largest-priority-first (water-filling, capped at each corridor's
    requirement). Barricades: keep the top `available_barricades` cordon
    points by betweenness. Tow trucks: one each to the highest-impact
    corridors.

    Returns {allocation, coverage_pct, officers_used, officers_required,
    unmet, barricades_used, tow_truck_corridors}.
    """
    corridors = [p["corridor"] for p in required_plan]
    required = {p["corridor"]: p["officers"] for p in required_plan}
    level = {p["corridor"]: p["impact_level"] for p in required_plan}
    total_required = sum(required.values())

    alloc = {c: 0 for c in corridors}
    budget = max(0, int(available_officers))

    if budget >= total_required:
        alloc = dict(required)  # full coverage
    else:
        # 1) guarantee one officer to each High-impact corridor (within budget).
        for c in sorted(corridors, key=lambda c: -_priority(c, level[c])):
            if budget <= 0:
                break
            if level[c] == "High" and required[c] > 0:
                alloc[c] = 1
                budget -= 1
        # 2) water-fill the rest by priority, one at a time, up to requirement.
        order = sorted(corridors, key=lambda c: -_priority(c, level[c]))
        progressed = True
        while budget > 0 and progressed:
            progressed = False
            for c in order:
                if budget <= 0:
                    break
                if alloc[c] < required[c]:
                    alloc[c] += 1
                    budget -= 1
                    progressed = True

    officers_used = sum(alloc.values())
    coverage = round(officers_used / total_required * 100) if total_required else 100

    # Barricades: keep the busiest cordon points within budget.
    ranked_barricades = sorted(barricade_points, key=lambda b: -b["betweenness"])
    kept = ranked_barricades[: max(0, int(available_barricades))]

    # Tow trucks: pre-position at the highest-impact corridors.
    tow_order = sorted(corridors, key=lambda c: -_priority(c, level[c]))
    tow_corridors = tow_order[: max(0, int(available_tow_trucks))]

    by_corridor = {p["corridor"]: p for p in required_plan}
    allocation = []
    for c in corridors:
        src = by_corridor[c]
        covered = alloc[c] >= required[c]
        if covered:
            reason = "Full requirement met"
        else:
            reason = (
                f"Budget-rationed: {alloc[c]} of {required[c]} "
                f"({level[c]}-impact corridors are served first)"
            )
        allocation.append(
            {
                "corridor": c,
                "officers": alloc[c],
                "required": required[c],
                "impact_level": level[c],
                "deploy_by": src["deploy_by"],
                "covered": covered,
                "rationale": src.get("rationale", ""),
                "allocation_reason": reason,
            }
        )

    return {
        "allocation": allocation,
        "coverage_pct": coverage,
        "officers_used": officers_used,
        "officers_required": total_required,
        "unmet": max(0, total_required - officers_used),
        "barricades_used": kept,
        "tow_truck_corridors": tow_corridors,
    }
