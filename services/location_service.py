
import requests
from fastapi import APIRouter, HTTPException, Query

from services.noaa_station_service import get_stations
from services.station_county_service import get_station_county

router = APIRouter()


def _get_stations() -> list[dict[str, object]]:
    try:
        return get_stations()
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"NOAA station request or response failed: {exc}",
        ) from exc

def get_states() -> list[str]:
    """Return the state codes that have NOAA tide-prediction stations."""
    return sorted(
        {
            station["state"].upper()
            for station in _get_stations()
            if isinstance(station.get("state"), str) and station["state"]
        }
    )

def get_cities_from_location(
    state: str = Query(..., description="The two-letter state code, e.g., FL"),
) -> list[dict[str, str | None]]:
    """Returns only the stations/cities that belong to the selected state."""
    return [
        {
            "id": station["id"],
            "name": station["name"],
            "county": get_station_county(station),
            "state": station["state"],
        }
        for station in _get_stations()
        if isinstance(station.get("state"), str)
        and station["state"].upper() == state.upper()
        and isinstance(station.get("id"), str)
        and isinstance(station.get("name"), str)
    ]
