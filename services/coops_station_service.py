
"""
coops_station_service.py

Find nearby NOAA CO-OPS stations that offer:
  - water_temperature
  - air_pressure

This module discovers stations and checks sensor availability.
It does NOT yet verify that the latest observation is fresh.
"""

from __future__ import annotations

import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

logger = logging.getLogger(__name__)

MDAPI_BASE = (
    "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi"
)

REQUEST_TIMEOUT_SECONDS = 20
CACHE_TTL_SECONDS = 24 * 60 * 60

# NOAA metadata changes infrequently, so cache station inventories
# and sensor metadata for 24 hours within this Python process.
_cache: dict[str, tuple[float, Any]] = {}


class CoopsAPIError(RuntimeError):
    """Raised when NOAA CO-OPS metadata cannot be retrieved."""


def _get_json(url: str) -> dict:
    """GET a NOAA JSON endpoint and validate the response."""
    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        data = response.json()

    except (requests.RequestException, ValueError) as exc:
        raise CoopsAPIError(
            f"Unable to retrieve NOAA CO-OPS data from {url}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise CoopsAPIError(f"Unexpected NOAA response from {url}")
    if "error" in data:
        raise CoopsAPIError(f"NOAA metadata error from {url}: {data['error']}")

    return data


def _get_cached_json(url: str) -> dict:
    """Return cached JSON unless the cache entry has expired."""
    now = time.monotonic()
    cached = _cache.get(url)

    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    data = _get_json(url)
    _cache[url] = (now, data)
    return data


def _station_list(station_type: str) -> list[dict]:
    """Retrieve active stations for a CO-OPS station type."""
    url = f"{MDAPI_BASE}/stations.json?type={station_type}"
    data = _get_cached_json(url)

    stations = data.get("stations", data.get("stationList"))

    if not isinstance(stations, list):
        raise CoopsAPIError(
            f"Unexpected station list response for type={station_type}"
        )

    if any(not isinstance(station, dict) for station in stations):
        raise CoopsAPIError(f"Invalid station metadata for type={station_type}")
    return stations


def _station_sensors(station_id: str) -> set[str]:
    """Retrieve active sensor names for a station."""
    url = f"{MDAPI_BASE}/stations/{station_id}/sensors.json"
    data = _get_cached_json(url)
    if "sensors" not in data:
        raise CoopsAPIError(f"Missing sensor metadata for station {station_id}")
    sensors = data["sensors"]
    if sensors is None:
        return set()
    if not isinstance(sensors, list):
        raise CoopsAPIError(f"Unexpected sensor response for station {station_id}")
    return {
        sensor["name"].strip().casefold()
        for sensor in sensors
        if isinstance(sensor, dict) and sensor.get("status") == 1
        and isinstance(sensor.get("name"), str)
    }


def _distance_miles(
    latitude1: float,
    longitude1: float,
    latitude2: float,
    longitude2: float,
) -> float:
    """Calculate great-circle distance between two coordinates."""
    earth_radius_miles = 3958.7613

    lat1 = math.radians(latitude1)
    lon1 = math.radians(longitude1)
    lat2 = math.radians(latitude2)
    lon2 = math.radians(longitude2)

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    return (
        2
        * earth_radius_miles
        * math.asin(math.sqrt(min(1.0, a)))
    )


def _candidate(
    station: dict,
    latitude: float,
    longitude: float,
    product_name: str,
) -> dict | None:
    """Build a candidate record if its coordinates are valid."""
    try:
        station_lat = float(station["lat"])
        station_lon = float(station["lng"])
        station_id = str(station["id"])
    except (KeyError, TypeError, ValueError):
        logger.warning("Skipping station with invalid metadata: %s", station)
        return None
    if (
        not station_id or not math.isfinite(station_lat) or not math.isfinite(station_lon)
        or not -90 <= station_lat <= 90 or not -180 <= station_lon <= 180
    ):
        logger.warning("Skipping station with invalid coordinates or ID: %s", station)
        return None

    distance = _distance_miles(
        latitude,
        longitude,
        station_lat,
        station_lon,
    )

    return {
        "station_id": station_id,
        "name": station.get("name"),
        "latitude": station_lat,
        "longitude": station_lon,
        "distance_miles": distance,
        "product": product_name,
        "state": station.get("state"),
        "timezone": station.get("timezone"),
    }


def find_nearest_coops_station(
    latitude: float,
    longitude: float,
    *,
    max_water_temp_distance_miles: float = 25,
    max_air_pressure_distance_miles: float = 50,
    candidate_limit: int = 5,
) -> dict:
    """
    Find nearby stations for water temperature and air pressure.

    Returns the nearest qualifying station for each product, plus
    a short list of alternatives.

    Distance limits are application screening rules, not NOAA standards.
    A nearby station may still be environmentally unrepresentative.
    """
    if not -90 <= latitude <= 90:
        raise ValueError("latitude must be between -90 and 90")

    if not -180 <= longitude <= 180:
        raise ValueError("longitude must be between -180 and 180")

    if not math.isfinite(max_water_temp_distance_miles) or max_water_temp_distance_miles <= 0:
        raise ValueError("Water-temperature distance must be positive")

    if not math.isfinite(max_air_pressure_distance_miles) or max_air_pressure_distance_miles <= 0:
        raise ValueError("Air-pressure distance must be positive")

    if candidate_limit < 1:
        raise ValueError("candidate_limit must be at least 1")

    # The met inventory includes stations without pressure sensors.
    water_temp_stations = _station_list("watertemp")
    met_stations = _station_list("met")

    water_temp_by_id = {
        str(station.get("id")): station
        for station in water_temp_stations
        if station.get("id")
    }

    met_by_id = {
        str(station.get("id")): station
        for station in met_stations
        if station.get("id")
    }

    # Only inspect stations close enough to be possible candidates.
    def nearby(stations: dict, max_distance: float) -> dict:
        result = {}

        for station_id, station in stations.items():
            candidate = _candidate(
                station, latitude, longitude, "candidate"
            )

            if (
                candidate
                and candidate["distance_miles"] <= max_distance
            ):
                result[station_id] = station

        return result

    nearby_water = nearby(
        water_temp_by_id, max_water_temp_distance_miles
    )
    nearby_met = nearby(
        met_by_id, max_air_pressure_distance_miles
    )

    # Check sensor metadata only for nearby stations.
    candidate_ids = sorted(set(nearby_water) | set(nearby_met))

    water_candidates = []
    pressure_candidates = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        sensor_sets = dict(zip(candidate_ids, executor.map(_station_sensors, candidate_ids)))

    for station_id, sensors in sensor_sets.items():
        if station_id in nearby_water and "water temperature" in sensors:
            candidate = _candidate(
                nearby_water[station_id],
                latitude,
                longitude,
                "water_temperature",
            )
            if candidate:
                water_candidates.append(candidate)

        if station_id in nearby_met and "barometric pressure" in sensors:
            candidate = _candidate(
                nearby_met[station_id],
                latitude,
                longitude,
                "air_pressure",
            )
            if candidate:
                pressure_candidates.append(candidate)

    water_candidates.sort(key=lambda item: (item["distance_miles"], item["station_id"]))
    pressure_candidates.sort(key=lambda item: (item["distance_miles"], item["station_id"]))

    nearest_water = water_candidates[0] if water_candidates else None
    nearest_pressure = (
        pressure_candidates[0] if pressure_candidates else None
    )

    same_station = None
    if nearest_water and nearest_pressure:
        if nearest_water["station_id"] == nearest_pressure["station_id"]:
            same_station = nearest_water["station_id"]

    return {
        "requested_location": {
            "latitude": latitude,
            "longitude": longitude,
        },
        "water_temperature": {
            "nearest": nearest_water,
            "alternatives": water_candidates[1:candidate_limit],
            "max_distance_miles": max_water_temp_distance_miles,
        },
        "air_pressure": {
            "nearest": nearest_pressure,
            "alternatives": pressure_candidates[1:candidate_limit],
            "max_distance_miles": max_air_pressure_distance_miles,
        },
        "same_station_for_both_products": same_station,
        "observations_verified": False,
        "environment_match_verified": False,
    }
