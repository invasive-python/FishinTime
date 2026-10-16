import requests


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
    return [station for station in stations if isinstance(station, dict)]


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
