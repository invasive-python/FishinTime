from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests


US_STATE_NAME_TO_CODE: dict[str, str] = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "Florida": "FL",
    "Georgia": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
}


def _state_matches(result: dict[str, Any], state: str) -> bool:
    admin1 = result.get("admin1")
    if not isinstance(admin1, str):
        return False

    requested_state = state.strip().casefold()
    state_name = next(
        (
            name
            for name, code in US_STATE_NAME_TO_CODE.items()
            if requested_state in (name.casefold(), code.casefold())
        ),
        state.strip(),
    )
    return admin1.casefold() == state_name.casefold()


def _find_city_result(
    data: dict[str, Any], state: str | None = None
) -> dict[str, Any] | None:
    results = data.get("results")
    if not isinstance(results, list):
        return None

    return next(
        (
            result
            for result in results
            if isinstance(result, dict)
            and (state is None or _state_matches(result, state))
        ),
        None,
    )


def get_long_lat_from_city(city_name: str, state_name: str) -> dict[str, Any] | None:
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": city_name, "count": 20, "countryCode": "US", }

    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict):
        raise ValueError("Geocoding response must be a JSON object.")

    return _find_city_result(data, state_name)


def get_city_data(
    city_name: str, state: str | None = None
) -> dict[str, Any] | None:
    url = "https://geocoding-api.open-meteo.com/v1/search"
    city_name = city_name.partition(",")[0].strip()
    params = {
        "name": city_name,
        "count": 20,
        "language": "en",
        "countryCode": "US"
    }

    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, dict):
        raise ValueError("Geocoding response must be a JSON object.")
    result = _find_city_result(data, state)
    if result is None:
        print("Location not found.")    
    return result


def get_location_timezone(location_data: dict[str, object]) -> ZoneInfo:
    timezone_name = location_data.get("timezone")
    if not isinstance(timezone_name, str) or not timezone_name:
        raise ValueError("Geocoding result does not contain a timezone.")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"Geocoding result contains an unknown timezone: {timezone_name}"
        ) from exc
