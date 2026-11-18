import math

import requests

from models.station import Station
from services.station_county_service import get_station_county

STATIONS_URL = (
    "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json"
)


def get_stations() -> list[dict[str, object]]:
    response = requests.get(
        STATIONS_URL,
        params={"type": "tidepredictions", "units": "english"},
        timeout=20,
    )
    response.raise_for_status()
    station_data = response.json()
    if not isinstance(station_data, dict):
        raise ValueError("NOAA station response must be a JSON object.")
    stations = station_data.get("stations")
    if not isinstance(stations, list):
        raise ValueError("NOAA station response must contain a stations list.")
    valid_stations = [station for station in stations if isinstance(station, dict)]
    return sorted(
        valid_stations, key=lambda station: (station["lat"], station["lng"])
    )


class AmbiguousStationError(ValueError):
    pass


def get_station(
    name: str, state: str, station_id: str | None = None
) -> Station | None:
    matches = [
        station
        for station in get_stations()
        if isinstance(station.get("state"), str)
        and station["state"].strip().casefold() == state.strip().casefold()
        and (
            station.get("id") == station_id
            if station_id is not None
            else isinstance(station.get("name"), str)
            and station["name"].strip().casefold() == name.strip().casefold()
        )
    ]
    if not matches:
        return None
    if len(matches) > 1:
        raise AmbiguousStationError(
            f"Multiple stations named {name!r} in {state}; specify station_id."
        )

    station = matches[0]
    station_id = station.get("id")
    station_name = station.get("name")
    station_state = station.get("state")
    lat = station.get("lat")
    lng = station.get("lng")
    if (
        not isinstance(station_id, str)
        or not station_id
        or not isinstance(station_name, str)
        or not station_name
        or not isinstance(station_state, str)
        or not isinstance(lat, (int, float))
        or not isinstance(lng, (int, float))
        or isinstance(lat, bool)
        or isinstance(lng, bool)
        or not math.isfinite(lat)
        or not math.isfinite(lng)
        or not -90 <= lat <= 90
        or not -180 <= lng <= 180
    ):
        raise ValueError(f"Invalid NOAA station data for {station_id!r}.")
    return Station(
        id=station_id,
        name=station_name,
        lat=float(lat),
        lng=float(lng),
        state=station_state,
        county=get_station_county(station),
    )


def get_station_id(city_name: str) -> str | None:
    normalized_name = city_name.strip().casefold()
    for station in get_stations():
        name = station.get("name")
        station_id = station.get("id")
        if (
            isinstance(name, str)
            and name.strip().casefold() == normalized_name
            and isinstance(station_id, str)
        ):
            return station_id
    return None

def get_station_id_by_coordinates(city_lat: float, city_long: float) -> str | None:
    for station in get_stations():
        station_id = station.get("id")
        station_lat = station.get("lat")
        station_long = station.get("lng")
        if (
#            isinstance(name, str)
#            and 
            station_lat == city_lat
            and station_long == city_long
        ):
            return station_id
    return None

