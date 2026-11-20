import re
from datetime import date as date_type, datetime, time
from zoneinfo import ZoneInfo

import requests


def get_moon_phase_data(date, coords, utc_offset_hours: float | None = None) -> dict:
    base_url = "https://aa.usno.navy.mil/api/rstt/oneday"
    temp_coords = str(coords)
    final_coords = re.sub("[()]", "", temp_coords)
    params = {
        "date": date,
        "coords": final_coords,
    }
    if utc_offset_hours is not None:
        params["tz"] = utc_offset_hours
    response = requests.get(base_url, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("USNO moon-phase response must be a JSON object.")
    if "error" in data:
        raise ValueError("USNO moon-phase response contains an error.")
    return data


def _utc_offset_hours(timezone_name: object, day: object) -> float | None:
    if not isinstance(timezone_name, str) or not timezone_name:
        return None
    parsed_day = day if isinstance(day, date_type) else date_type.fromisoformat(str(day))
    local_noon = datetime.combine(parsed_day, time(12), tzinfo=ZoneInfo(timezone_name))
    offset = local_noon.utcoffset()
    return offset.total_seconds() / 3600 if offset is not None else None


def get_moon_phase_from_city_data(city_data, date) -> dict:
    lat = city_data["latitude"]
    lon = city_data["longitude"]
    coords = lat, lon

    # With the station's UTC offset, USNO returns rise and set times in local time.
    moon_phase_data = get_moon_phase_data(
        date, coords, _utc_offset_hours(city_data.get("timezone"), date)
    )
    properties = moon_phase_data.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise ValueError("USNO moon-phase response is missing its properties.")
    return properties