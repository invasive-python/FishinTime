from datetime import date as date_type

import services.city_data_service as city_service
import services.moon_phase_service as moon
import services.noaa_station_service as noaa_stations
import services.tides_service as tides
import services.waves_service as waves
import services.weather_service as weather
import services.pressure_forecaster as pressure

from models.weather_schemas import ForecastResponse


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


def serve_forecast(city, state, date):
    parsed_date = _normalize_date(date)
    try:
        city_norm = city.partition(",")[0].strip()
        forecast = weather.get_forecast(city_norm, state, parsed_date)
        city_data = city_service.get_city_data(city_norm, state)
        if not city_data:
            return None

        lat = city_data["latitude"]
        long = city_data["longitude"]

        location_timezone = city_service.get_location_timezone(city_data)
        phase_data = moon.get_moon_phase_from_city_data(city_data, parsed_date)

        station_id = noaa_stations.get_station_id(city)
        if station_id is None:
            return None

        tide_data = tides.get_tides_from_station_id_and_dates(
            station_id, parsed_date.isoformat()
        )

        waves_data = waves.get_waves_data(lat, long, location_timezone,
        )

        pressure_data = pressure.get_fishing_pressure_trend(lat, long)

        if not forecast or not getattr(forecast, "periods", None):
            return None
        if not tide_data or not phase_data:
            return None

        forecast_period = forecast.periods[0]
        detailed_forecast = forecast_period.detailed_forecast
        precipitation = forecast_period.precipitation_probability or 0
        start_time = forecast_period.start_time.astimezone(
            location_timezone
        ).strftime("%Y-%m-%d %H:%M")
        temperature = forecast_period.temperature
        fahrenheit = ((temperature * 1.8) + 32) if temperature is not None else 0

        wind_speed = forecast_period.wind_speed or {}
        wind_speed_max = float(wind_speed.get("maxValue", wind_speed.get("value", 0)))
        wind_speed_min = float(wind_speed.get("minValue", wind_speed.get("value", 0)))
        conversion_factor = 0.621371

        closest_phase = _nested_lookup(phase_data, "data", "closestphase") or {}
        closest_date = "-".join(
            str(part)
            for part in (
                closest_phase.get("year"),
                closest_phase.get("month"),
                closest_phase.get("day"),
            )
        )

        return ForecastResponse(
            city=city,
            date=str(parsed_date),
            precipitation_probability=int(precipitation),
            start_time=start_time,
            temp=int(round(fahrenheit)),
            wind_speed_max=round(wind_speed_max * conversion_factor, 2),
            wind_speed_min=round(wind_speed_min * conversion_factor, 2),
            wind_direction=forecast_period.wind_direction or "",
            moon_current_phase=str(
                _nested_lookup(phase_data, "data", "curphase")
                or _nested_lookup(phase_data, "curphase")
                or ""
            ),
            moon_closest_phase=str(closest_phase.get("phase") or ""),
            moon_closest_phase_date=closest_date,
            moon_brightness=str(
                _nested_lookup(phase_data, "data", "fracillum")
                or _nested_lookup(phase_data, "fracillum")
                or 0.0
            ),
            predictions=tide_data,
            detailed_forecast=detailed_forecast,
            ai_evaluation="",
            waves=waves_data,
            pressure = pressure_data,
        )

    except Exception as e:
        print(e)
        raise