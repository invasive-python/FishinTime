from datetime import UTC, datetime
import logging
import math
from zoneinfo import ZoneInfo

import requests

from models.weather_schemas import WaterTemperatureObservation

COOPS_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
logger = logging.getLogger(__name__)


def _get_observations(
    station_id: str, product: str, date_params: dict[str, str],
) -> tuple[list[tuple[datetime, float]], str | None]:
    response = requests.get(
        COOPS_URL,
        params={
            **date_params, "station": station_id, "product": product,
            "time_zone": "gmt", "units": "english", "format": "json",
            "application": "FishinTime",
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"NOAA {product} response must be a JSON object.")
    if "error" in payload:
        error = payload["error"]
        message = error.get("message") if isinstance(error, dict) else str(error)
        return [], str(message)
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError(f"NOAA {product} response is missing observations.")

    observations = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError(f"NOAA {product} observation must be an object.")
        if item.get("v") in (None, ""):
            continue
        try:
            observed = datetime.strptime(item["t"], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            value = float(item["v"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"NOAA {product} observation has an invalid time or value.") from exc
        if not math.isfinite(value):
            raise ValueError(f"NOAA {product} observation has a non-finite value.")
        observations.append((observed, value))
    observations.sort()
    return observations, None


def get_recent_observations(station_id: str, product: str) -> tuple[list[tuple[datetime, float]], str | None]:
    return _get_observations(station_id, product, {"date": "recent"})


def get_observations_for_interval(
    station_id: str, product: str, start: datetime, end: datetime,
) -> tuple[list[tuple[datetime, float]], str | None]:
    return _get_observations(station_id, product, {
        "begin_date": start.astimezone(UTC).strftime("%Y%m%d %H:%M"),
        "end_date": end.astimezone(UTC).strftime("%Y%m%d %H:%M"),
    })


def get_water_temperature(station_id: str, location_timezone: ZoneInfo) -> WaterTemperatureObservation:
    try:
        observations, error = get_recent_observations(station_id, "water_temperature")
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Unable to retrieve water temperature for station %s: %s", station_id, exc)
        return WaterTemperatureObservation(error=f"Water temperature unavailable: {exc}")
    if error:
        return WaterTemperatureObservation(error=f"Water temperature unavailable: {error}")
    if not observations:
        return WaterTemperatureObservation(error="No water temperature observations available.")
    observed_at, temperature = observations[-1]
    return WaterTemperatureObservation(
        observed_at=observed_at.astimezone(location_timezone),
        temperature_f=temperature,
    )
