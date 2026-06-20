"""Live weather provider -- WeatherAPI.com.

Turns current/forecast conditions at a coordinate into a congestion
multiplier (>= 1.0) for the fusion score's weather term. Rain, low
visibility and high wind all slow traffic, so they push the multiplier up.

Key is read from WEATHER_API_KEY (env / .env). On no key or any failure it
returns a neutral factor (1.0, is_mock=True) so the pipeline never breaks --
same graceful-fallback contract as modules.tomtom_client.

  GET http://api.weatherapi.com/v1/current.json?key=..&q=lat,lon
  GET http://api.weatherapi.com/v1/forecast.json?key=..&q=lat,lon&days=N
"""
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

logger = logging.getLogger("trafficsense.weather")

WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY")
BASE = "http://api.weatherapi.com/v1"

_CACHE_TTL_S = 600  # 10 min
_cache = {}  # (lat, lon, hour) -> (timestamp, result)

# Multiplier ceiling -- weather can add at most +50% pressure.
_MAX_FACTOR = 1.5


def has_live_key() -> bool:
    return bool(WEATHER_API_KEY)


def _neutral():
    return {"factor": 1.0, "condition": None, "precip_mm": None, "vis_km": None, "is_mock": True}


def _factor_from(precip_mm, chance_rain, vis_km, wind_kph) -> float:
    """Map conditions to a multiplier in [1.0, 1.5]."""
    f = 1.0
    if precip_mm is not None:
        f += min(0.25, precip_mm * 0.05)          # steady rain
    if chance_rain is not None:
        f += (chance_rain / 100.0) * 0.10          # likelihood of rain
    if vis_km is not None and vis_km < 5:
        f += 0.15 if vis_km < 2 else 0.08          # fog / heavy rain haze
    if wind_kph is not None and wind_kph > 40:
        f += 0.05                                  # gusty
    return round(min(_MAX_FACTOR, f), 3)


def get_weather_factor(lat: float, lon: float, when: datetime = None) -> dict:
    """Returns {factor, condition, precip_mm, vis_km, is_mock}. `when` in the
    future uses the forecast for that hour; otherwise current conditions."""
    if not (WEATHER_API_KEY and lat is not None and lon is not None):
        return _neutral()

    hour_key = when.strftime("%Y%m%d%H") if when else "now"
    cache_key = (round(lat, 3), round(lon, 3), hour_key)
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[0] < _CACHE_TTL_S:
        return cached[1]

    try:
        q = f"{lat},{lon}"
        future = when is not None and when > datetime.now()
        if future:
            days = min(14, max(1, (when.date() - datetime.now().date()).days + 1))
            resp = httpx.get(f"{BASE}/forecast.json", params={"key": WEATHER_API_KEY, "q": q, "days": days}, timeout=6.0)
            resp.raise_for_status()
            data = resp.json()
            block = _forecast_hour(data, when)
        else:
            resp = httpx.get(f"{BASE}/current.json", params={"key": WEATHER_API_KEY, "q": q}, timeout=6.0)
            resp.raise_for_status()
            block = resp.json()["current"]

        precip = block.get("precip_mm")
        vis = block.get("vis_km")
        wind = block.get("wind_kph")
        chance = block.get("chance_of_rain")  # present on forecast hours
        result = {
            "factor": _factor_from(precip, chance, vis, wind),
            "condition": (block.get("condition") or {}).get("text"),
            "precip_mm": precip,
            "vis_km": vis,
            "is_mock": False,
        }
        _cache[cache_key] = (time.time(), result)
        return result
    except Exception as e:
        logger.warning("WeatherAPI call failed (%s,%s): %r -- neutral", lat, lon, e)
        return _neutral()


def _forecast_hour(data, when):
    """Pick the forecast hour block closest to `when`, falling back to the
    day block or current conditions."""
    for day in data.get("forecast", {}).get("forecastday", []):
        if day.get("date") == when.strftime("%Y-%m-%d"):
            hours = day.get("hour", [])
            for h in hours:
                if h.get("time", "").endswith(f"{when.hour:02d}:00"):
                    return h
            if hours:
                return hours[min(when.hour, len(hours) - 1)]
    return data.get("current", {})
