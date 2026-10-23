
import requests
from fastapi import APIRouter, HTTPException, Query

from services.noaa_station_service import get_stations

router = APIRouter()


def _get_stations() -> list[dict[str, object]]:
    try:
        return get_stations()
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"NOAA station request or response failed: {exc}",
        ) from exc


# @router.get(
#     "/forecast/get_location",
#     response_model=LocationResponse,
#     summary="Get monitoring locations for a state",
#     tags=["get_forecast"],
# )
# def get_location(state: str) -> LocationResponse:
#     filtered_stations = [
#         station
#         for station in _get_stations()
#         if isinstance(station.get("state"), str)
#         and station["state"].upper() == state.upper()
#     ]
#     return LocationResponse(state=state, stations=filtered_stations)


@router.get("/api/states", response_model=list[str])
def get_states() -> list[str]:
    """Return the state codes that have NOAA tide-prediction stations."""
    return sorted(
        {
            station["state"].upper()
            for station in _get_stations()
            if isinstance(station.get("state"), str) and station["state"]
        }
    )


@router.get("/api/cities", response_model=list[dict[str, str]])
def get_cities_from_location(
    state: str = Query(..., description="The two-letter state code, e.g., FL"),
) -> list[dict[str, str]]:
    """Returns only the stations/cities that belong to the selected state."""
    return [
        {"id": station["id"], "name": station["name"]}
        for station in _get_stations()
        if isinstance(station.get("state"), str)
        and station["state"].upper() == state.upper()
        and isinstance(station.get("id"), str)
        and isinstance(station.get("name"), str)
    ]
