from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from models.weather_schemas import MarineForecastSeries, NearshoreForecast
from services.weather_service import _parse_duration


def _value_at(series: MarineForecastSeries, timestamp: datetime) -> float | None:
    for interval in series.values:
        if interval.valid_start <= timestamp < interval.valid_start + _parse_duration(interval.duration):
            return interval.value
    return None


def get_waves_data(
    nearshore: NearshoreForecast | None,
    location_timezone: ZoneInfo,
    start_date: date,
    *,
    forecast_days: int = 7,
) -> pd.DataFrame | None:
    if not 1 <= forecast_days <= 7:
        raise ValueError("Forecast days must be between 1 and 7.")
    if nearshore is None:
        return None
    start = datetime.combine(start_date, time.min, tzinfo=location_timezone)
    end = datetime.combine(
        start_date + timedelta(days=forecast_days), time.min, tzinfo=location_timezone
    )
    timestamps = pd.date_range(start=start, end=end, freq="h", inclusive="left")
    return pd.DataFrame({
        "date": timestamps,
        "wave_height": [_value_at(nearshore.wave_height, timestamp) for timestamp in timestamps],
        "wave_period": [_value_at(nearshore.wave_period, timestamp) for timestamp in timestamps],
        "wave_direction": [_value_at(nearshore.wave_direction, timestamp) for timestamp in timestamps],
    })
