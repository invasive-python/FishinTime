import math
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

from models.weather_schemas import (
    MarineForecastSeries,
    MarineForecastValue,
    NearshoreForecast,
    NearshoreGridLocation,
)
from services.weather_service import NWS_HEADERS, _parse_valid_time, get_grid_data

GRIDPOINT_URL = "https://api.weather.gov/gridpoints/{office}/{x},{y}"
FORECAST_ZONE_URL = "https://api.weather.gov/zones/forecast"
INFERRED_DISTANCE_THRESHOLD_KM = 2.5
GRID_CELL_SIZE_KM = 2.5
METERS_TO_FEET = 3.28084

_SERIES_FIELDS = {
    "waveHeight": ("wave_height", "ft"),
    "wavePeriod": ("wave_period", "s"),
    "waveDirection": ("wave_direction", "degrees"),
    "primarySwellHeight": ("primary_swell_height", "ft"),
    "primarySwellPeriod": ("primary_swell_period", "s"),
    "primarySwellDirection": ("primary_swell_direction", "degrees"),
    "secondarySwellHeight": ("secondary_swell_height", "ft"),
    "secondarySwellPeriod": ("secondary_swell_period", "s"),
    "secondarySwellDirection": ("secondary_swell_direction", "degrees"),
    "windWaveHeight": ("wind_wave_height", "ft"),
    "windWavePeriod": ("wind_wave_period", "s"),
    "windWaveDirection": ("wind_wave_direction", "degrees"),
    "windSpeed": ("wind_speed", "mph"),
    "windDirection": ("wind_direction", "degrees"),
}
def _get_series_values(
    properties: dict[str, Any],
    field: str,
    target_unit: str,
    window_start: datetime,
    window_end: datetime,
) -> MarineForecastSeries:
    payload = properties.get(field)
    if payload is None:
        return MarineForecastSeries(unit=target_unit)
    if not isinstance(payload, dict):
        raise ValueError(f"NWS grid response field {field!r} must be an object.")
    values = payload.get("values")
    if not isinstance(values, list):
        raise ValueError(f"NWS grid response field {field!r} has no values list.")

    series_values = []
    for item in values:
        if not isinstance(item, dict):
            raise ValueError(f"NWS grid response field {field!r} has an invalid value.")
        valid_start, duration, duration_text = _parse_valid_time(item.get("validTime"))
        valid_end = valid_start + duration
        if valid_start >= window_end or valid_end <= window_start:
            continue

        raw_value = item.get("value")
        if raw_value is not None and (
            not isinstance(raw_value, (int, float))
            or isinstance(raw_value, bool)
            or not math.isfinite(raw_value)
        ):
            raise ValueError(f"NWS grid response field {field!r} has a nonnumeric value.")
        series_values.append(
            MarineForecastValue(
                valid_start=valid_start,
                duration=duration_text,
                value=(
                    _convert_value(float(raw_value), payload.get("uom"), target_unit)
                    if raw_value is not None
                    else None
                ),
            )
        )

    return MarineForecastSeries(unit=target_unit, values=series_values)


def _convert_value(value: float, source_unit: object, target_unit: str) -> float:
    unit = source_unit.lower() if isinstance(source_unit, str) else ""
    if target_unit == "ft":
        if unit in {"wmounit:m", "m"}:
            return value * METERS_TO_FEET
        if "ft" in unit:
            return value
        raise ValueError(f"Unsupported NWS wave-height unit: {source_unit!r}")
    if target_unit == "mph":
        if "km_h-1" in unit or "km/h" in unit:
            return value * 0.621371
        if "m_s-1" in unit or "m/s" in unit:
            return value * 2.236936
        if "mph" in unit:
            return value
        raise ValueError(f"Unsupported NWS wind-speed unit: {source_unit!r}")
    if target_unit == "s":
        if not unit:
            raise ValueError("NWS wave-period value is missing its unit.")
        if not unit.endswith(":s") and unit != "s":
            raise ValueError(f"Unsupported NWS wave-period unit: {source_unit!r}")
    if target_unit == "degrees":
        if not unit:
            raise ValueError("NWS direction value is missing its unit.")
        if "degree" not in unit:
            raise ValueError(f"Unsupported NWS direction unit: {source_unit!r}")
    return value


def _grid_center(data: dict[str, Any]) -> tuple[float, float]:
    geometry = data.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        raise ValueError("NWS gridpoint response is missing its polygon geometry.")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        raise ValueError("NWS gridpoint polygon has no coordinates.")
    ring = coordinates[0]
    if not isinstance(ring, list) or len(ring) < 4:
        raise ValueError("NWS gridpoint polygon has an invalid outer ring.")
    vertices = ring[:-1] if ring[0] == ring[-1] else ring
    if not vertices:
        raise ValueError("NWS gridpoint polygon has no vertices.")
    longitudes = []
    latitudes = []
    for vertex in vertices:
        if (
            not isinstance(vertex, list)
            or len(vertex) < 2
            or not isinstance(vertex[0], (int, float))
            or not isinstance(vertex[1], (int, float))
            or not math.isfinite(vertex[0])
            or not math.isfinite(vertex[1])
        ):
            raise ValueError("NWS gridpoint polygon contains an invalid vertex.")
        longitudes.append(float(vertex[0]))
        latitudes.append(float(vertex[1]))
    return sum(latitudes) / len(latitudes), sum(longitudes) / len(longitudes)


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = lat2_rad - lat1_rad
    delta_lon = math.radians(lon2 - lon1)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad)
        * math.cos(lat2_rad)
        * math.sin(delta_lon / 2) ** 2
    )
    return 6371.0 * 2 * math.asin(math.sqrt(min(1.0, haversine)))


def _has_marine_series(data: dict[str, Any]) -> bool:
    properties = data.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("NWS gridpoint response is missing its properties object.")
    for field in ("waveHeight", "wavePeriod"):
        payload = properties.get(field)
        values = payload.get("values") if isinstance(payload, dict) else None
        if not isinstance(values, list):
            return False
        valid_values = [
            item
            for item in values
            if isinstance(item, dict)
            and isinstance(item.get("value"), (int, float))
            and not isinstance(item.get("value"), bool)
            and isinstance(item.get("validTime"), str)
        ]
        if len(valid_values) < 2:
            return False
    return True


def _is_coastal_gridpoint(lat: float, lon: float) -> bool:
    response = requests.get(
        FORECAST_ZONE_URL,
        params={"point": f"{lat},{lon}"},
        headers=NWS_HEADERS,
        timeout=20,
    )
    if response.status_code == 404:
        return False
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("NWS forecast-zone response must be a JSON object.")
    features = data.get("features")
    if not isinstance(features, list):
        raise ValueError("NWS forecast-zone response is missing its features list.")
    return any(
        isinstance(feature, dict)
        and isinstance(feature.get("properties"), dict)
        and feature["properties"].get("type") == "coastal"
        for feature in features
    )


def _fetch_gridpoint(office: str, x: int, y: int) -> dict[str, Any] | None:
    response = requests.get(
        GRIDPOINT_URL.format(office=office, x=x, y=y),
        headers=NWS_HEADERS,
        timeout=20,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("NWS gridpoint response must be a JSON object.")
    return data


def _find_nearest_marine_gridpoint(
    office: str,
    origin_x: int,
    origin_y: int,
    station_lat: float,
    station_lon: float,
    max_distance_km: float,
) -> tuple[int, int, float, float, float] | None:
    max_radius = math.ceil(max_distance_km / GRID_CELL_SIZE_KM)
    for radius in range(max_radius + 1):
        offsets = (
            [(0, 0)]
            if radius == 0
            else [
                (dx, dy)
                for dy in range(-radius, radius + 1)
                for dx in range(-radius, radius + 1)
                if max(abs(dx), abs(dy)) == radius
            ]
        )
        with ThreadPoolExecutor(max_workers=min(8, len(offsets))) as executor:
            gridpoints = list(
                executor.map(
                    lambda offset: (
                        offset,
                        _fetch_gridpoint(
                            office,
                            origin_x + offset[0],
                            origin_y + offset[1],
                        ),
                    ),
                    offsets,
                )
            )

        candidates = []
        for (dx, dy), data in gridpoints:
            if data is None or not _has_marine_series(data):
                continue
            grid_lat, grid_lon = _grid_center(data)
            distance = _distance_km(
                station_lat, station_lon, grid_lat, grid_lon
            )
            if distance > max_distance_km:
                continue
            if _is_coastal_gridpoint(grid_lat, grid_lon):
                candidates.append(
                    (
                        distance,
                        origin_x + dx,
                        origin_y + dy,
                        grid_lat,
                        grid_lon,
                    )
                )
        if candidates:
            distance, x, y, grid_lat, grid_lon = min(candidates)
            return x, y, grid_lat, grid_lon, distance
    return None


def _get_grid_location(
    lat: float, lon: float, max_distance_km: float
) -> NearshoreGridLocation | None:
    point_data = get_grid_data(lat, lon)
    properties = point_data.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("NWS point response is missing its properties object.")
    office = properties.get("gridId")
    x = properties.get("gridX")
    y = properties.get("gridY")
    if (
        not isinstance(office, str)
        or not office
        or not isinstance(x, int)
        or isinstance(x, bool)
        or not isinstance(y, int)
        or isinstance(y, bool)
    ):
        raise ValueError("NWS point response has invalid forecast grid coordinates.")

    nearest = _find_nearest_marine_gridpoint(
        office, x, y, lat, lon, max_distance_km
    )
    if nearest is None:
        return None
    grid_x, grid_y, grid_lat, grid_lon, distance = nearest
    return NearshoreGridLocation(
        office=office,
        x=grid_x,
        y=grid_y,
        lat=grid_lat,
        lng=grid_lon,
        distance_km=distance,
        inferred=distance > INFERRED_DISTANCE_THRESHOLD_KM,
    )


def get_nearshore_conditions(
    lat: float,
    lon: float,
    requested_date: date,
    location_timezone: ZoneInfo,
    *,
    forecast_days: int = 7,
    max_distance_km: float = 10.0,
) -> NearshoreForecast | None:
    if not 1 <= forecast_days <= 7:
        raise ValueError("Forecast days must be between 1 and 7.")
    if not math.isfinite(max_distance_km) or max_distance_km <= 0:
        raise ValueError("Maximum marine-grid distance must be a positive number.")

    grid = _get_grid_location(lat, lon, max_distance_km)
    if grid is None:
        return None

    data = _fetch_gridpoint(grid.office, grid.x, grid.y)
    if data is None:
        raise ValueError("Selected NWS marine gridpoint is no longer available.")
    properties = data.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("NWS gridpoint response is missing its properties object.")

    window_start = datetime.combine(
        requested_date, time.min, tzinfo=location_timezone
    ).astimezone(UTC)
    window_end = datetime.combine(
        requested_date + timedelta(days=forecast_days),
        time.min,
        tzinfo=location_timezone,
    ).astimezone(UTC)
    series = {
        output_name: _get_series_values(
            properties, source_name, unit, window_start, window_end
        )
        for source_name, (output_name, unit) in _SERIES_FIELDS.items()
    }

    return NearshoreForecast(
        source="NWS forecastGridData",
        timezone=location_timezone.key,
        forecast_days=forecast_days,
        grid=grid,
        **series,
    )
