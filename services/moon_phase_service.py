import re

import requests


def get_moon_phase_data(date, coords) -> dict:
    base_url = "https://aa.usno.navy.mil/api/rstt/oneday"
    temp_coords = str(coords)
    final_coords = re.sub("[()]", "", temp_coords)
    params = {
        "date": date,
        "coords": final_coords,
    }
    response = requests.get(base_url, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("USNO moon-phase response must be a JSON object.")
    if "error" in data:
        raise ValueError("USNO moon-phase response contains an error.")
    return data


def get_moon_phase_from_city_data(city_data, date) -> dict:
    lat = city_data["latitude"]
    lon = city_data["longitude"]
    coords = lat, lon

    moon_phase_data = get_moon_phase_data(date, coords)
    properties = moon_phase_data.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise ValueError("USNO moon-phase response is missing its properties.")
    return properties