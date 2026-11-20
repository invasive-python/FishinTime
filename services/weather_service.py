import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, NotRequired, Required, TypedDict
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from fastapi import HTTPException

from models.weather_schemas import (
    ForecastPeriod,
    PrecipitationCondition,
    PrecipitationInterval,
    WeatherResponse,
)

NWS_HEADERS = {
    "Accept": "application/geo+json",
    "User-Agent": "FishinTime/1.0 (https://tidalfishintime.com)",
}

_DURATION_PATTERN = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)
_PRECIPITATION_TYPES = {
    "drizzle", "freezing_drizzle", "freezing_rain", "hail", "ice_crystals",
    "rain", "rain_showers", "sleet", "snow", "snow_showers",
}


def _parse_duration(value: str) -> timedelta:
    if not isinstance(value, str) or not _DURATION_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid NWS forecast duration: {value!r}")
    try:
        duration = pd.Timedelta(value).to_pytimedelta()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid NWS forecast duration: {value!r}") from exc
    if duration <= timedelta(0):
        raise ValueError(f"NWS forecast duration must be positive: {value!r}")
    return duration


def _parse_valid_time(value: object) -> tuple[datetime, timedelta, str]:
    if not isinstance(value, str) or "/" not in value:
        raise ValueError("NWS forecast value is missing its valid-time interval.")
    start_text, duration_text = value.split("/", maxsplit=1)
    try:
        start = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("NWS forecast value has an invalid valid-time start.") from exc
    if start.tzinfo is None:
        raise ValueError("NWS forecast valid-time start must include a timezone.")
    return start.astimezone(UTC), _parse_duration(duration_text), duration_text


def get_precipitation_intervals(
    grid_url: str, start_date: date, forecast_days: int, timezone: str,
) -> list[PrecipitationInterval]:
    response = requests.get(grid_url, headers=NWS_HEADERS, timeout=20)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("properties"), dict):
        raise ValueError("NWS grid response is missing its properties object.")
    layer = data["properties"].get("weather")
    if layer is None:
        return []
    if not isinstance(layer, dict) or not isinstance(layer.get("values"), list):
        raise ValueError("NWS weather grid is missing its values list.")

    zone = ZoneInfo(timezone)
    window_start = datetime.combine(start_date, time.min, tzinfo=zone).astimezone(UTC)
    window_end = datetime.combine(
        start_date + timedelta(days=forecast_days), time.min, tzinfo=zone
    ).astimezone(UTC)
    intervals = []
    for item in layer["values"]:
        if not isinstance(item, dict):
            raise ValueError("NWS weather grid contains an invalid interval.")
        start, duration, _ = _parse_valid_time(item.get("validTime"))
        end = start + duration
        if start >= window_end or end <= window_start:
            continue
        values = item.get("value")
        if values is None:
            continue
        if not isinstance(values, list):
            raise ValueError("NWS weather grid interval must contain a list.")
        conditions = []
        for value in values:
            if not isinstance(value, dict):
                raise ValueError("NWS weather grid contains an invalid condition.")
            weather = value.get("weather")
            attributes = value.get("attributes")
            if weather in _PRECIPITATION_TYPES or (
                weather == "thunderstorms"
                and isinstance(attributes, list)
                and "heavy_rain" in attributes
            ):
                conditions.append(PrecipitationCondition(
                    weather=weather, coverage=value.get("coverage")
                ))
        if conditions:
            intervals.append(PrecipitationInterval(
                start_time=start, end_time=end, conditions=conditions
            ))
    return sorted(intervals, key=lambda interval: interval.start_time)


class _NoaaProbability(TypedDict, total=False):
    value: int | None


class _NoaaTemperature(TypedDict, total=False):
    unitCode: str | None
    value: float | None


class _NoaaPeriod(TypedDict, total=False):
    name: Required[str]
    startTime: Required[str]
    endTime: Required[str]
    temperature: NotRequired[float | _NoaaTemperature | None]
    temperatureUnit: NotRequired[str | None]
    windSpeed: NotRequired[dict | None]
    windDirection: NotRequired[str | None]
    probabilityOfPrecipitation: NotRequired[_NoaaProbability | None]
    detailedForecast: NotRequired[str | None]


def _map_noaa_period(period: _NoaaPeriod) -> ForecastPeriod:
    precipitation = period.get("probabilityOfPrecipitation")
    if precipitation is not None and not isinstance(precipitation, dict):
        raise ValueError("Forecast precipitation data must be an object.")

    temperature = period.get("temperature")
    if isinstance(temperature, dict):
        temperature_value = temperature.get("value")
        temperature_unit = temperature.get("unitCode")
    else:
        temperature_value = temperature
        temperature_unit = period.get("temperatureUnit")

    return ForecastPeriod(
        name=period["name"],
        start_time=datetime.fromisoformat(period["startTime"]),
        end_time=datetime.fromisoformat(period["endTime"]),
        temperature=temperature_value,
        temperature_unit=temperature_unit,
        wind_speed=period.get("windSpeed"),
        wind_direction=period.get("windDirection"),
        precipitation_probability=(
            precipitation.get("value") if precipitation is not None else None
        ),
        detailed_forecast=period.get("detailedForecast"),
    )


def get_grid_data(lat: float, lon: float) -> dict[str, Any]:
    url = f"https://api.weather.gov/points/{lat},{lon}"
    response = requests.get(url, headers=NWS_HEADERS, timeout=20)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Gridpoint response must be a JSON object.")
    return data


def get_forecast(
    lat: float, lon: float, date: date, *, forecast_days: int = 1,
    allow_empty: bool = False,
) -> WeatherResponse:
    try:
        grid_data = get_grid_data(lat, lon)
        timezone = grid_data["properties"]["timeZone"]
        if not isinstance(timezone, str) or not timezone:
            raise ValueError("Gridpoint response is missing its timezone.")
        if not 1 <= forecast_days <= 7:
            raise ValueError("Forecast days must be between 1 and 7.")
        periods = get_forecast_data(
            {"latitude": lat, "longitude": lon},
            date,
            forecast_days=forecast_days,
            grid_data=grid_data,
        )
        if not periods and not allow_empty:
            raise HTTPException(
                status_code=404,
                detail=f"No forecast is available for {date.isoformat()}",
            )

        grid_url = grid_data["properties"].get("forecastGridData")
        if not isinstance(grid_url, str) or not grid_url:
            raise ValueError("Gridpoint response is missing its forecastGridData URL.")
        precipitation_intervals = get_precipitation_intervals(
            grid_url, date, forecast_days, timezone
        )
        return WeatherResponse(
            timezone=timezone,
            date=date,
            periods=[_map_noaa_period(period) for period in periods],
            precipitation_intervals=precipitation_intervals,
        )
    except HTTPException:
        raise
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Weather provider request or response failed: {exc}",
        ) from exc


def get_forecast_data(
    city_data: dict[str, Any],
    requested_date: date,
    *,
    forecast_days: int = 1,
    grid_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not 1 <= forecast_days <= 7:
        raise ValueError("Forecast days must be between 1 and 7.")
    lat = city_data["latitude"]
    lon = city_data["longitude"]
    if grid_data is None:
        grid_data = get_grid_data(lat, lon)
    grid_properties = grid_data["properties"]
    grid_x = grid_properties["gridX"]
    grid_y = grid_properties["gridY"]
    office = grid_properties["gridId"]

    url = (
        f"https://api.weather.gov/gridpoints/{office}/"
        f"{grid_x},{grid_y}/forecast?units=us"
    )
    response = requests.get(
        url,
        timeout=20,
        headers={
            **NWS_HEADERS,
            "Feature-Flags": "forecast_temperature_qv,forecast_wind_speed_qv",
        },
    )
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict):
        raise ValueError("Forecast response must be a JSON object.")
    properties = data.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("Forecast response is missing its properties object.")
    periods = properties.get("periods")
    if not isinstance(periods, list):
        raise ValueError("Forecast response is missing its periods list.")

    first_date = requested_date
    last_date = requested_date + timedelta(days=forecast_days)
    matching_periods = []
    for period in periods:
        if not isinstance(period, dict) or not isinstance(period.get("startTime"), str):
            raise ValueError("Forecast response contains an invalid period.")
        try:
            period_date = datetime.fromisoformat(period["startTime"]).date()
        except ValueError as exc:
            raise ValueError("Forecast response contains an invalid start time.") from exc
        if first_date <= period_date < last_date:
            matching_periods.append(period)
    return matching_periods
