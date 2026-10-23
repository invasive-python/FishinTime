from datetime import datetime

import requests

from models.weather_schemas import PressureTrend


def get_fishing_pressure_trend(lat: float, lon: float) -> PressureTrend:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "pressure_msl",
        "current": "pressure_msl",
        "past_days": 1,  # Ensures we have historical data points to look backward
        "forecast_days": 1
    }
    
    try:
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.JSONDecodeError:
        content_type = response.headers.get("Content-Type", "unknown")
        body_preview = response.text[:200].replace("\n", " ")
        return PressureTrend(
            error=(
                f"Expected JSON but received {content_type} "
                f"(HTTP {response.status_code}). Response begins: {body_preview!r}"
            )
        )
    except requests.exceptions.RequestException as e:
        return PressureTrend(error=f"Error fetching API data: {e}")

    try:
        current = data["current"]
        hourly = data["hourly"]
        current_pressure = float(current["pressure_msl"])
        current_time = datetime.fromisoformat(current["time"])
        hourly_times = [
            datetime.fromisoformat(hourly_time)
            for hourly_time in hourly["time"]
        ]
        hourly_pressures = hourly["pressure_msl"]
        if len(hourly_times) != len(hourly_pressures):
            raise ValueError("Hourly pressure times and values have different lengths.")
        current_index = max(
            index
            for index, hourly_time in enumerate(hourly_times)
            if hourly_time <= current_time
        )
        if current_index < 3:
            raise IndexError("Three hours of prior pressure data are unavailable.")
        pressure_3_hours_ago = float(hourly_pressures[current_index - 3])
    except (KeyError, TypeError, ValueError, IndexError) as e:
        return PressureTrend(error=f"Invalid pressure API response: {e}")

    delta = current_pressure - pressure_3_hours_ago

    if delta < -1.0:
        trend = "Falling rapidly"
        outlook = (
            "Excellent: a pre-frontal pressure drop may indicate increased feeding."
        )
    elif delta < -0.2:
        trend = "Falling steadily"
        outlook = "Good: falling pressure may indicate an active feeding window."
    elif delta > 1.0:
        trend = "Rising rapidly"
        outlook = "Poor: rapidly rising pressure may slow fish activity."
    elif delta > 0.2:
        trend = "Rising steadily"
        outlook = "Fair: the bite may be slowing; adjust bait and location."
    else:
        trend = "Stable"
        outlook = "Neutral: rely on tides and structure to find feeding fish."

    return PressureTrend(
        current_pressure_hpa=current_pressure,
        pressure_3_hours_ago_hpa=pressure_3_hours_ago,
        change_3h_hpa=delta,
        trend=trend,
        outlook=outlook,
    )
