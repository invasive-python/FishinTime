from zoneinfo import ZoneInfo

import openmeteo_requests
import pandas as pd
import requests_cache
from retry_requests import retry

# Setup the Open-Meteo API client with cache and retry on error
cache_session = requests_cache.CachedSession('.cache', expire_after = 3600)
retry_session = retry(cache_session, retries = 5, backoff_factor = 0.2)
openmeteo = openmeteo_requests.Client(session = retry_session)


def get_waves_data(
    lat: float, long: float, location_timezone: ZoneInfo
) -> pd.DataFrame | None:
    url = "https://marine-api.open-meteo.com/v1/marine?"
    params = {
        "latitude": lat,
        "longitude": long,
        "hourly": [
            "wave_height",
            "wave_direction",
            "wave_period",
            "sea_level_height_msl",
        ],
        "forecast_days": "1",
    }

    responses = openmeteo.weather_api(url, params = params)
    response = responses[0]
    # Process hourly data. The order of variables needs to be the same as requested.
    hourly = response.Hourly()
    hourly_wave_height = hourly.Variables(0).ValuesAsNumpy()
    hourly_wave_direction = hourly.Variables(1).ValuesAsNumpy()
    hourly_wave_period = hourly.Variables(2).ValuesAsNumpy()
    hourly_sea_level_height_msl = hourly.Variables(3).ValuesAsNumpy()

    hourly_data = {
        "date": pd.date_range(
            start=pd.to_datetime(
                hourly.Time(), unit="s", utc=True
            ).tz_convert(location_timezone),
            end=pd.to_datetime(
                hourly.TimeEnd(), unit="s", utc=True
            ).tz_convert(location_timezone),
            freq = pd.Timedelta(seconds = hourly.Interval()),
            inclusive = "left"
        )
    }

    hourly_data["wave_height"] = hourly_wave_height
    hourly_data["wave_direction"] = hourly_wave_direction
    hourly_data["wave_period"] = hourly_wave_period
    hourly_data["sea_level_height_msl"] = hourly_sea_level_height_msl

    hourly_dataframe = pd.DataFrame(data = hourly_data)
    print("\nHourly data\n", hourly_dataframe)

    return hourly_dataframe
