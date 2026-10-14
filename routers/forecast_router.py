import requests
from datetime import datetime
from fastapi import APIRouter, HTTPException
import services.forecast_service as forecast_service

from models.weather_schemas import ForecastResponse, LocationResponse

router = APIRouter()

def is_today_or_future(date_string: str, date_format: str = "%Y-%m-%d") -> bool:
    try:
        input_date = datetime.strptime(date_string, date_format).date()
        today = datetime.today().date()
        
        return input_date >= today
        
    except ValueError:
        return False


@router.get(
    "/forecast/get_location",
    response_model=LocationResponse,
    summary="Get forecast periods for a city and date",
    tags=["get_forecast"],
)
def get_location(state: str) -> LocationResponse:
    try:
        response = requests.get(
            "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json",
            params={"type": "tidepredictions", "units": "english"},
            timeout=20,
        )
        response.raise_for_status()
        station_data = response.json()
        if not isinstance(station_data, dict):
            raise ValueError("NOAA station response must be a JSON object.")
        stations = station_data.get("stations", [])
        if not isinstance(stations, list):
            raise ValueError("NOAA station response must contain a stations list.")

        fl_stations = [
            station
            for station in stations
            if isinstance(station, dict) and station.get("state") == state
        ]

        return LocationResponse(state=state, stations=fl_stations)
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"NOAA station request or response failed: {exc}",
        ) from exc


@router.get(
    "/forecast/get_forecast",
    response_model=ForecastResponse,
    summary="Get forecast periods for a city and date",
    tags=["get_forecast"],
)
def get_forecast(city: str, date: str) -> ForecastResponse:
    try:
        valid_date = is_today_or_future(date)

        if valid_date:

            forecast = forecast_service.serve_forecast(city, date)

            if forecast:
                print(f"{forecast.city} Fishing Forecast for {forecast.date}:")
                print("----------------------")
                print("precipitation: " + str(forecast.precipitation_probability) + "% chance")
                print("temperature: " + str(forecast.temp) + "°F")
                print("wind speed (max): " + str(forecast.wind_speed_max) + " mph")
                print("wind speed (min): " + str(forecast.wind_speed_min) + " mph")
                print("wind direction: " + forecast.wind_direction)
                print("current moon phase: " + forecast.moon_current_phase)
                print("next moon phase: (" + forecast.moon_closest_phase_date + ") " + forecast.moon_closest_phase)
                print("moon brightness: " + forecast.moon_brightness)

                return forecast

    except HTTPException:
        raise
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Weather provider request or response failed: {exc}",
        ) from exc 
