from datetime import date, datetime
from fastapi import APIRouter, HTTPException
from models.weather_schemas import ForecastPeriod, WeatherResponse
from services.city_data_service import get_long_lat_from_city
from typing import Any, NotRequired, Required, TypedDict

import requests


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
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Gridpoint response must be a JSON object.")
    return data


def get_forecast(city: str, state: str, date: date) -> WeatherResponse:
    try:
        city_data = get_long_lat_from_city(city, state)
        if city_data is None:
            raise HTTPException(status_code=404, detail="City not found")

        periods = get_forecast_data(city_data, date)
        if not periods:
            raise HTTPException(
                status_code=404,
                detail=f"No forecast is available for {date.isoformat()}",
            )

        return WeatherResponse(
            city=city,
            date=date,
            periods=[_map_noaa_period(period) for period in periods],
        )
    except HTTPException:
        raise
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Weather provider request or response failed: {exc}",
        ) from exc


def get_forecast_data(
    city_data: dict[str, Any], requested_date: date
) -> list[dict[str, Any]]:
    lat = city_data["latitude"]
    lon = city_data["longitude"]
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
            "accept": "application/geo+json",
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

    requested_date_string = requested_date.isoformat()
    matching_periods = []
    for period in periods:
        if not isinstance(period, dict) or not isinstance(period.get("startTime"), str):
            raise ValueError("Forecast response contains an invalid period.")
        if period["startTime"].startswith(requested_date_string):
            matching_periods.append(period)
    return matching_periods
