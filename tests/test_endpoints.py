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
    assert body["is_route_event"] is False
    assert body["route_length_km"] is None
    for c in body["affected_corridors"]:
        assert c["impact_level"] in {"Low", "Medium", "High"}


def test_event_impact_route(client):
    """Rally/road show: end_lat/end_lon turns the point event into a
    route-following corridor instead of a circular blast radius."""
    resp = client.post(
        "/event-impact",
        json={
            "name": "Independence Day Rally",
            "lat": 12.9716,
            "lon": 77.5946,
            "attendance": 15000,
            "event_type": "rally",
            "start_time": "2026-08-15T09:00:00",
            "end_lat": 12.9915,
            "end_lon": 77.6090,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_route_event"] is True
    assert body["route_length_km"] > 0
    assert len(body["affected_corridors"]) > 0
    assert len(body["manpower_plan"]) == len(body["affected_corridors"])
    for b in body["barricade_points"]:
        assert b["priority"] in {"HIGH", "MEDIUM"}


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
