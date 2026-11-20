from datetime import timedelta
import logging
from zoneinfo import ZoneInfo

import requests

from models.weather_schemas import PressureTrend
from services.coops_observations_service import (
    get_observations_for_interval, get_recent_observations,
)

MBAR_PER_INHG = 33.8638866667
logger = logging.getLogger(__name__)


def _pressure_trend(current: float, previous: float) -> PressureTrend:
    delta = current - previous
    if delta < -0.02953:
        trend = "Falling rapidly"
        outlook = "Excellent: a pre-frontal pressure drop may indicate increased feeding."
    elif delta < -0.005906:
        trend = "Falling steadily"
        outlook = "Good: falling pressure may indicate an active feeding window."
    elif delta > 0.02953:
        trend = "Rising rapidly"
        outlook = "Poor: rapidly rising pressure may slow fish activity."
    elif delta > 0.005906:
        trend = "Rising steadily"
        outlook = "Fair: the bite may be slowing; adjust bait and location."
    else:
        trend = "Stable"
        outlook = "Neutral: rely on tides and structure to find feeding fish."
    return PressureTrend(
        current_pressure_inhg=current,
        pressure_3_hours_ago_inhg=previous,
        change_3h_inhg=delta,
        trend=trend,
        outlook=outlook,
    )


def get_fishing_pressure_trend(station_id: str, location_timezone: ZoneInfo) -> PressureTrend:
    observations, error = get_recent_observations(station_id, "air_pressure")
    if error:
        return PressureTrend(source="NOAA CO-OPS", error=f"Pressure unavailable: {error}")
    if not observations:
        return PressureTrend(source="NOAA CO-OPS", error="No pressure observations available.")
    observations = [(observed, value / MBAR_PER_INHG) for observed, value in observations]
    latest_time, latest_value = observations[-1]
    target_time = latest_time - timedelta(hours=3)
    prior = [item for item in observations if item[0] <= target_time]
    history_error = None
    if not prior or target_time - prior[-1][0] > timedelta(minutes=12):
        try:
            history, history_error = get_observations_for_interval(
                station_id, "air_pressure", target_time - timedelta(minutes=12), target_time
            )
            if history_error:
                logger.warning("Pressure history unavailable for station %s: %s",
                               station_id, history_error)
                history_error = "NOAA returned an error; see server logs for details."
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Unable to retrieve pressure history for station %s: %s", station_id, exc)
            history, history_error = [], "Request failed; see server logs for details."
        prior = [
            (observed, value / MBAR_PER_INHG)
            for observed, value in history if observed <= target_time
        ]
    if prior and target_time - prior[-1][0] <= timedelta(minutes=12):
        result = _pressure_trend(latest_value, prior[-1][1])
    else:
        result = PressureTrend(
            current_pressure_inhg=latest_value,
            error=(
                f"Pressure history lookup failed: {history_error}"
                if history_error else "Pressure observation from three hours earlier is unavailable."
            ),
        )
    result.source = "NOAA CO-OPS"
    result.observed_at = latest_time.astimezone(location_timezone)
    return result
