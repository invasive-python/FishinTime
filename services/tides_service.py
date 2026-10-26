from datetime import date, timedelta

import requests


def get_tide_data(station_id: str, begin_date: str, end_date: str) -> dict:
    base_url = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
    params = {
        "begin_date": begin_date,
        "end_date": end_date,
        "station": station_id,
        "product": "predictions",
        "datum": "MLLW",
        "time_zone": "lst_ldt",
        "interval": "hilo",
        "units": "english",
        "application": "DataAPI_Sample",
        "format": "json",
    }
    response = requests.get(base_url, params=params, timeout=20)
    response.raise_for_status()
    tide_data = response.json()
    if not isinstance(tide_data, dict):
        raise ValueError("NOAA tide response must be a JSON object.")
    if "error" in tide_data:
        raise ValueError("NOAA tide response contains an error.")
    if not isinstance(tide_data.get("predictions"), list):
        raise ValueError("NOAA tide response is missing its predictions list.")
    return tide_data


def get_tides_from_station_id_and_dates(
    station_id: str, parsed_date: str
) -> list[dict]:
    requested_date = date.fromisoformat(parsed_date)
    begin_date = (requested_date - timedelta(days=1)).strftime("%Y%m%d")
    end_date = (requested_date + timedelta(days=2)).strftime("%Y%m%d")

    tide_data = get_tide_data(station_id, begin_date, end_date)
    return tide_data["predictions"]
