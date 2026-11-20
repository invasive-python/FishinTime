from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, date as date_type, datetime, time, timedelta
import logging
from typing import Callable, TypeVar
from zoneinfo import ZoneInfo

import requests

import services.city_data_service as city_service
import services.coops_observations_service as coops
import services.coops_station_service as coops_stations
import services.moon_phase_service as moon
import services.noaa_station_service as noaa_stations
import services.nearshore_conditions_service as nearshore
import services.nws_alerts_service as nws_alerts
import services.tides_service as tides
import services.waves_service as waves
import services.weather_service as weather
import services.pressure_forecaster as pressure

from models.weather_schemas import (
    DailyForecast, ForecastResponse, ObservationStation, PressureTrend,
    WaterTemperatureObservation,
)

logger = logging.getLogger(__name__)
Observation = TypeVar("Observation", PressureTrend, WaterTemperatureObservation)


def _get_nearby_observation(
    stations_future: Future,
    product: str,
    location_timezone: ZoneInfo,
    lookup: Callable[[str, ZoneInfo], Observation],
    observation_type: type[Observation],
    has_value: Callable[[Observation], bool],
) -> Observation:
    try:
        stations = stations_future.result()
    except coops_stations.CoopsAPIError as exc:
        logger.warning("Unable to find nearby NOAA stations: %s", exc)
        return observation_type(
            source="NOAA CO-OPS",
            error="Station lookup unavailable. See server logs for details.",
        )

    product_stations = stations[product]
    candidates = [product_stations["nearest"], *product_stations["alternatives"]]
    failures = []
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            result = lookup(candidate["station_id"], location_timezone)
        except (requests.RequestException, ValueError) as exc:
            logger.warning("NOAA %s lookup failed for station %s: %s",
                           product, candidate["station_id"], exc)
            failures.append(f"{candidate.get('name') or 'Nearby station'}: request failed")
            continue
        if has_value(result):
            result.station = ObservationStation.model_validate(candidate)
            return result
        logger.warning("NOAA %s unavailable for station %s: %s",
                       product, candidate["station_id"], result.error or "No observations")
        failures.append(f"{candidate.get('name') or 'Nearby station'}: observation unavailable")
    detail = "; ".join(failures) if failures else "No eligible nearby station was found."
    return observation_type(
        source="NOAA CO-OPS",
        error=f"No usable nearby {product.replace('_', ' ')} observations. {detail}",
    )


def _normalize_date(value):
    if isinstance(value, str):
        return date_type.fromisoformat(value)
    return value


def _nested_lookup(mapping, *keys):
    current = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _event_time(phase_data, body_key, phenomenon):
    events = _nested_lookup(phase_data, "data", body_key) or _nested_lookup(phase_data, body_key)
    for event in events if isinstance(events, list) else []:
        if isinstance(event, dict) and event.get("phen") == phenomenon:
            return event.get("time")
    return None


def _daily_forecast(
    day, period, phase_data, pressure_data, location_timezone, precipitation_intervals
):
    closest = _nested_lookup(phase_data, "data", "closestphase") or {}
    closest_parts = [closest.get(key) for key in ("year", "month", "day")]
    closest_date = (
        "-".join(str(part) for part in closest_parts)
        if all(part is not None for part in closest_parts) else None
    )
    moon_phase = (
        _nested_lookup(phase_data, "data", "curphase")
        or _nested_lookup(phase_data, "curphase")
    )
    brightness = _nested_lookup(phase_data, "data", "fracillum")
    if brightness is None:
        brightness = _nested_lookup(phase_data, "fracillum")

    daily = DailyForecast(
        date=day,
        moon_current_phase=str(moon_phase) if moon_phase is not None else None,
        moon_closest_phase=closest.get("phase"),
        moon_closest_phase_date=closest_date,
        moon_brightness=str(brightness) if brightness is not None else None,
        sunrise=_event_time(phase_data, "sundata", "Rise"),
        sunset=_event_time(phase_data, "sundata", "Set"),
        moonrise=_event_time(phase_data, "moondata", "Rise"),
        moonset=_event_time(phase_data, "moondata", "Set"),
        pressure=pressure_data,
    )
    day_start = datetime.combine(day, time.min, tzinfo=location_timezone).astimezone(UTC)
    day_end = datetime.combine(
        day + timedelta(days=1), time.min, tzinfo=location_timezone
    ).astimezone(UTC)
    starts = [
        max(interval.start_time, day_start)
        for interval in precipitation_intervals
        if interval.start_time < day_end and interval.end_time > day_start
    ]
    if starts:
        daily.start_time = min(starts).astimezone(location_timezone).strftime("%Y-%m-%d %H:%M")
    if period is None:
        return daily

    temperature = period.temperature
    unit = (period.temperature_unit or "").lower()
    if temperature is not None and ("degc" in unit or unit in {"c", "celsius"}):
        temperature = temperature * 1.8 + 32
    wind = period.wind_speed or {}
    wind_unit = str(wind.get("unitCode", "")).lower()
    conversion = (
        2.236936 if "m_s-1" in wind_unit or "m/s" in wind_unit
        else 0.621371 if "km_h-1" in wind_unit or "km/h" in wind_unit
        else 1.15078 if "knot" in wind_unit else 1.0
    )
    max_speed = wind.get("maxValue", wind.get("value"))
    min_speed = wind.get("minValue", wind.get("value"))
    daily.precipitation_probability = period.precipitation_probability
    daily.temp = round(temperature) if temperature is not None else None
    daily.wind_speed_max = round(float(max_speed) * conversion, 2) if max_speed is not None else None
    daily.wind_speed_min = round(float(min_speed) * conversion, 2) if min_speed is not None else None
    daily.wind_direction = period.wind_direction
    daily.detailed_forecast = period.detailed_forecast
    return daily


def serve_forecast(city, state, date, station_id=None, *, start_date=None):
    parsed_date = _normalize_date(date)
    forecast_days = 7
    window_start = _normalize_date(start_date) if start_date else parsed_date
    if not window_start <= parsed_date < window_start + timedelta(days=forecast_days):
        raise ValueError("Selected date must be within the seven-day forecast window.")
    try:
        station = noaa_stations.get_station(city, state, station_id)
        if station is None:
            return None

        city_lat = station.lat
        city_long = station.lng
        dates = [window_start + timedelta(days=offset) for offset in range(forecast_days)]
        with ThreadPoolExecutor(max_workers=12) as executor:
            observation_stations_future = executor.submit(
                coops_stations.find_nearest_coops_station, city_lat, city_long
            )
            forecast_future = executor.submit(
                weather.get_forecast, city_lat, city_long, window_start,
                forecast_days=forecast_days, allow_empty=True,
            )
            tides_future = executor.submit(
                tides.get_tides_for_date_range, station.id, window_start, forecast_days
            )
            forecast = forecast_future.result()
            city_data = {
                "latitude": city_lat,
                "longitude": city_long,
                "timezone": forecast.timezone,
            }
            location_timezone = city_service.get_location_timezone(city_data)
            alerts_future = executor.submit(
                nws_alerts.get_active_alerts, [(city_lat, city_long)], station.state,
                station.county, location_timezone.key,
            )
            nearshore_future = executor.submit(
                nearshore.get_nearshore_conditions, city_lat, city_long, window_start,
                location_timezone, forecast_days=forecast_days,
            )
            pressure_future = executor.submit(
                _get_nearby_observation, observation_stations_future, "air_pressure",
                location_timezone, pressure.get_fishing_pressure_trend, PressureTrend,
                lambda observation: observation.current_pressure_inhg is not None,
            )
            water_temperature_future = executor.submit(
                _get_nearby_observation, observation_stations_future, "water_temperature",
                location_timezone, coops.get_water_temperature, WaterTemperatureObservation,
                lambda observation: observation.temperature_f is not None,
            )
            phase_futures = [
                executor.submit(moon.get_moon_phase_from_city_data, city_data, day)
                for day in dates
            ]
            tide_data = tides_future.result()
            nearshore_data = nearshore_future.result()
            marine_alerts_future = None
            if nearshore_data is not None and (
                round(nearshore_data.grid.lat, 4), round(nearshore_data.grid.lng, 4)
            ) != (round(city_lat, 4), round(city_long, 4)):
                marine_alerts_future = executor.submit(
                    nws_alerts.get_active_alerts,
                    [(nearshore_data.grid.lat, nearshore_data.grid.lng)], None, None,
                    location_timezone.key,
                )
            pressure_data = pressure_future.result()
            water_temperature_data = water_temperature_future.result()
            phases = [future.result() for future in phase_futures]
            active_alerts = alerts_future.result()
            if marine_alerts_future is not None:
                active_alerts = nws_alerts.merge_active_alerts(
                    active_alerts, marine_alerts_future.result()
                )

        waves_data = waves.get_waves_data(
            nearshore_data, location_timezone, window_start,
            forecast_days=forecast_days,
        )

        daily_pressure = [
            pressure_data
            if pressure_data.observed_at and pressure_data.observed_at.date() == day
            else PressureTrend(
                source="NOAA CO-OPS",
                error=(
                    f"{pressure_data.error} Pressure forecasts are unavailable."
                    if pressure_data.observed_at is None and pressure_data.error
                    else "No pressure observation for this date; pressure forecasts are unavailable."
                ),
            )
            for day in dates
        ]

        if not tide_data:
            return None

        periods_by_day = {}
        for period in forecast.periods:
            local_date = period.start_time.astimezone(location_timezone).date()
            periods_by_day.setdefault(local_date, period)
        daily_forecasts = [
            _daily_forecast(
                day, periods_by_day.get(day), phase, daily_pressure[index],
                location_timezone, forecast.precipitation_intervals,
            )
            for index, (day, phase) in enumerate(zip(dates, phases))
        ]
        selected = daily_forecasts[dates.index(parsed_date)]

        return ForecastResponse(
            city=station.name,
            city_lat=str(city_lat),
            city_long=str(city_long),
            date=str(parsed_date),
            precipitation_probability=selected.precipitation_probability,
            start_time=selected.start_time,
            temp=selected.temp,
            water_temperature=water_temperature_data,
            wind_speed_max=selected.wind_speed_max,
            wind_speed_min=selected.wind_speed_min,
            wind_direction=selected.wind_direction,
            moon_current_phase=selected.moon_current_phase or "",
            moon_closest_phase=selected.moon_closest_phase or "",
            moon_closest_phase_date=selected.moon_closest_phase_date or "",
            moon_brightness=selected.moon_brightness or "",
            predictions=tide_data,
            station={
                "id": station.id,
                "name": station.name,
                "state": station.state,
                "lat": station.lat,
                "lng": station.lng,
                "county": station.county,
            },
            forecast_start_date=window_start,
            daily_forecasts=daily_forecasts,
            weather_forecast=forecast.periods,
            precipitation_forecast=forecast.precipitation_intervals,
            nearshore=nearshore_data,
            timezone=location_timezone.key,
            alerts=active_alerts,
            detailed_forecast=selected.detailed_forecast,
            ai_evaluation="",
            waves=waves_data,
            pressure = pressure_data,
        )

    except Exception as e:
        print(e)
        raise