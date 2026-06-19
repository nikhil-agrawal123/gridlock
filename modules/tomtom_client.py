"""TomTom Traffic Flow API client -- Flow Segment Data v4.

When TOMTOM_API_KEY is set (env var or a .env file), get_speeds() queries
the live Flow Segment Data endpoint for the road segment nearest a
corridor's coordinates and returns the real-time speed deviation. With no
key (or on any API failure) it falls back to a deterministic mock so the
rest of the pipeline still has a signal; the `is_mock` flag makes clear
which path produced the number.

Docs: https://docs.tomtom.com/traffic-api/documentation/tomtom-maps/v1/
      traffic-flow/flow-segment-data

  GET https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json
      ?key=<KEY>&point=<lat>,<lon>&unit=kmph
  -> flowSegmentData: { currentSpeed, freeFlowSpeed, currentTravelTime,
                        freeFlowTravelTime, confidence, roadClosure, ... }
"""
import hashlib
import logging
import os
import time
from datetime import datetime

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("trafficsense.tomtom")

TOMTOM_API_KEY = os.environ.get("TOMTOM_API_KEY")
# style=absolute, zoom=10, format=json  (see docs URL template above)
FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"

# TomTom's free tier is rate-limited; the scheduler hits every corridor
# every 15 min and the dashboard refetches on load, so cache each point's
# response briefly to collapse redundant calls.
_CACHE_TTL_S = 120
_cache = {}  # (lat, lon) -> (timestamp, result)


def has_live_key() -> bool:
    """True if a TomTom API key is configured (live data available)."""
    return bool(TOMTOM_API_KEY)


def _mock_speed_deviation(corridor: str, hour: int) -> float:
    """Deterministic pseudo-random deviation in [0, 1], worse at peak hours."""
    h = int(hashlib.sha256(corridor.encode()).hexdigest(), 16) % 100 / 100.0
    peak_boost = 0.25 if (4 <= hour < 7 or 19 <= hour < 23) else 0.0
    return min(1.0, h * 0.6 + peak_boost)


def _mock_result(corridor: str) -> dict:
    return {
        "current_speed": None,
        "free_flow_speed": None,
        "deviation": round(_mock_speed_deviation(corridor, datetime.now().hour), 3),
        "confidence": None,
        "road_closure": False,
        "is_mock": True,
    }


def get_speeds(corridor: str, lat: float = None, lon: float = None) -> dict:
    """Live Flow Segment Data for the segment nearest (lat, lon), else a
    deterministic mock (no key / no coords / call failed).

    Returns {current_speed, free_flow_speed, deviation, confidence,
    road_closure, is_mock}. `deviation` is in [0, 1]: 0 = free-flowing,
    1 = stopped or road closed.
    """
    if not (TOMTOM_API_KEY and lat is not None and lon is not None):
        return _mock_result(corridor)

    cache_key = (round(lat, 5), round(lon, 5))
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[0] < _CACHE_TTL_S:
        return cached[1]

    try:
        resp = httpx.get(
            FLOW_URL,
            params={"point": f"{lat},{lon}", "key": TOMTOM_API_KEY, "unit": "kmph"},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()["flowSegmentData"]

        current = data.get("currentSpeed")
        free_flow = data.get("freeFlowSpeed")
        road_closure = bool(data.get("roadClosure", False))
        if road_closure:
            deviation = 1.0
        elif free_flow and current is not None:
            deviation = max(0.0, (free_flow - current) / free_flow)
        else:
            deviation = 0.0

        result = {
            "current_speed": current,
            "free_flow_speed": free_flow,
            "deviation": round(deviation, 3),
            "confidence": data.get("confidence"),
            "road_closure": road_closure,
            "is_mock": False,
        }
        _cache[cache_key] = (time.time(), result)
        return result
    except httpx.HTTPStatusError as e:
        logger.warning(
            "TomTom HTTP %s for %s (%s,%s) -- using mock",
            e.response.status_code, corridor, lat, lon,
        )
    except Exception as e:  # network error, malformed payload, etc.
        logger.warning("TomTom call failed for %s (%r) -- using mock", corridor, e)
    return _mock_result(corridor)
