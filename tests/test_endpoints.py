"""Day 5.2 -- pytest coverage for the TrafficSense API.

Run from the project root: `pytest tests/ -v`. The first test that touches
the road graph pays a one-time ~25s load cost (cached for the rest of the
session via modules.graph_utils' lru_cache).
"""
import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_corridor_risk(client):
    resp = client.get("/corridor-risk/Mysore Road")
    assert resp.status_code == 200
    body = resp.json()
    assert body["corridor"] == "Mysore Road"
    assert body["impact_level"] in {"Low", "Medium", "High"}
    assert 0 <= body["composite_score"] <= 100


def test_corridors_all(client):
    resp = client.get("/corridors/all")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 21
    assert {"corridor", "lat", "lon", "impact_level", "composite_score"} <= body[0].keys()


def test_event_impact(client):
    resp = client.post(
        "/event-impact",
        json={
            "name": "Test Event",
            "lat": 12.9794,
            "lon": 77.5996,
            "attendance": 40000,
            "event_type": "sports",
            "start_time": "2026-06-25T19:00:00",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["affected_corridors"]) > 0
    assert len(body["manpower_plan"]) == len(body["affected_corridors"])
    assert body["blast_radius_km"] > 0
    for c in body["affected_corridors"]:
        assert c["impact_level"] in {"Low", "Medium", "High"}
        assert 0 <= c["event_risk_score"] <= 100  # weather folded into the score
    # cordon barricades ring the venue
    for b in body["barricade_points"]:
        assert b["priority"] in {"HIGH", "MEDIUM"}
    # weather is attached (live or neutral fallback)
    assert 1.0 <= body["weather"]["factor"] <= 1.5
    # historical-blockage prediction runs alongside the blast radius
    assert "corridors" in body["historical_blockage"]
    assert "hotspots" in body["historical_blockage"]
    # emergency route is either established or explicitly null
    assert "emergency_route" in body


def test_event_impact_route(client):
    """Moving event (rally): end_lat/end_lon makes it a route with barricades
    spread along the procession, not a circular blast zone."""
    resp = client.post(
        "/event-impact",
        json={
            "name": "Republic Day Rally",
            "lat": 12.9750, "lon": 77.6050,
            "end_lat": 12.9716, "end_lon": 77.6190,
            "attendance": 15000,
            "event_type": "rally",
            "start_time": "2026-06-22T09:00:00",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_route_event"] is True
    assert body["route_length_km"] > 0
    assert len(body["affected_corridors"]) > 0


def test_event_impact_resource_optimizer(client):
    """A constrained officer budget is never exceeded, and coverage drops
    below 100% with High-impact corridors prioritized."""
    resp = client.post(
        "/event-impact",
        json={
            "name": "Budgeted Event",
            "lat": 12.9794,
            "lon": 77.5996,
            "attendance": 40000,
            "event_type": "sports",
            "start_time": "2026-06-25T19:00:00",
            "available_officers": 12,
            "available_barricades": 4,
            "available_tow_trucks": 3,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assigned = sum(p["officers"] for p in body["optimized_plan"])
    assert assigned <= 12
    assert body["officers_used"] == assigned
    assert 0 <= body["coverage_pct"] <= 100
    assert len(body["barricade_points"]) <= 4
    assert len(body["tow_truck_corridors"]) <= 3


def test_activate_phase2(client):
    create_resp = client.post(
        "/event-impact",
        json={
            "name": "Phase2 Test Event",
            "lat": 12.9794,
            "lon": 77.5996,
            "attendance": 40000,
            "event_type": "sports",
            "start_time": "2026-06-25T19:00:00",
        },
    )
    event_id = create_resp.json()["event_id"]

    resp = client.post(f"/event/activate-phase2/{event_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "Phase 2 active"
    assert len(body["monitoring"]) > 0


def test_activate_phase2_unknown_event(client):
    resp = client.post("/event/activate-phase2/does-not-exist")
    assert resp.status_code == 200
    assert resp.json()["status"] == "error"


def test_weather_factor_bounds():
    """The weather multiplier stays within [1.0, 1.5] across conditions."""
    from modules.weather import _factor_from

    assert _factor_from(0, 0, 10, 5) == 1.0                 # clear
    heavy = _factor_from(30, 95, 1.0, 60)                   # storm
    assert 1.0 <= heavy <= 1.5


def test_score_breakdown_sums_to_score():
    """The explainable breakdown's components add up to the fixed score."""
    from modules.fusion import compute_score_fixed, score_breakdown

    dev, risk, ev, wx = 0.5, 0.4, 1.3, 1.2
    bd = score_breakdown(dev, risk, ev, wx)
    assert abs(bd["total"] - compute_score_fixed(dev, risk, ev, wx)) < 0.2
    assert abs(sum(c["points"] for c in bd["components"]) - bd["total"]) < 0.2


def test_resource_optimizer_respects_budget():
    """optimize_allocation never assigns more officers than available."""
    from modules.resource_optimizer import optimize_allocation

    plan = [
        {"corridor": "MG Road", "officers": 6, "impact_level": "High", "deploy_by": "17:00"},
        {"corridor": "Mysore Road", "officers": 3, "impact_level": "Medium", "deploy_by": "18:00"},
        {"corridor": "Hosur Road", "officers": 2, "impact_level": "Low", "deploy_by": "18:30"},
    ]
    out = optimize_allocation(plan, available_officers=5, available_barricades=10,
                              barricade_points=[], available_tow_trucks=1)
    assert sum(a["officers"] for a in out["allocation"]) <= 5
    assert out["officers_used"] <= 5
    # High-impact corridor is served before the Low one
    served = {a["corridor"]: a["officers"] for a in out["allocation"]}
    assert served["MG Road"] >= served["Hosur Road"]
