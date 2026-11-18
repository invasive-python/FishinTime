import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _load_counties() -> dict[str, object]:
    path = Path(__file__).with_name("station_counties.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Station county lookup must be a JSON object.")
    return data


def get_station_county(station: dict[str, object]) -> str | None:
    station_id = station.get("id")
    if not isinstance(station_id, str):
        return None
    entry = _load_counties().get(station_id)
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise ValueError(f"Invalid county lookup for station {station_id}.")
    if any(entry.get(key) != station.get(key) for key in ("lat", "lng", "state")):
        return None
    county = entry.get("county")
    if county is not None and not isinstance(county, str):
        raise ValueError(f"Invalid county name for station {station_id}.")
    return county
