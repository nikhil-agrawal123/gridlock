"""TomTom Traffic API client.

Reads TOMTOM_API_KEY from the environment; if unset (no key provisioned for
this hackathon build), falls back to a deterministic mock so the rest of the
pipeline (fusion scoring, dashboard) still has a signal to work with. The
mock is clearly flagged via `is_mock` so callers/judges can see it's not a
live read.
"""
import hashlib
import os

import httpx

TOMTOM_API_KEY = os.environ.get("TOMTOM_API_KEY")
FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"


def _mock_speed_deviation(corridor: str, hour: int) -> float:
    """Deterministic pseudo-random deviation in [0, 1], worse at peak hours."""
    h = int(hashlib.sha256(corridor.encode()).hexdigest(), 16) % 100 / 100.0
    peak_boost = 0.25 if (4 <= hour < 7 or 19 <= hour < 23) else 0.0
    return min(1.0, h * 0.6 + peak_boost)


def get_speeds(corridor: str, lat: float = None, lon: float = None) -> dict:
    """Returns {'current_speed', 'free_flow_speed', 'deviation', 'is_mock'}."""
    from datetime import datetime

    if TOMTOM_API_KEY and lat is not None and lon is not None:
        try:
            resp = httpx.get(
                FLOW_URL,
                params={"point": f"{lat},{lon}", "key": TOMTOM_API_KEY},
                timeout=5.0,
            )
            resp.raise_for_status()
            data = resp.json()["flowSegmentData"]
            current = data["currentSpeed"]
            free_flow = data["freeFlowSpeed"]
            deviation = max(0.0, (free_flow - current) / free_flow) if free_flow else 0.0
            return {
                "current_speed": current,
                "free_flow_speed": free_flow,
                "deviation": round(deviation, 3),
                "is_mock": False,
            }
        except Exception:
            pass  # fall through to mock on any API/network failure

    deviation = _mock_speed_deviation(corridor, datetime.now().hour)
    return {
        "current_speed": None,
        "free_flow_speed": None,
        "deviation": round(deviation, 3),
        "is_mock": True,
    }
