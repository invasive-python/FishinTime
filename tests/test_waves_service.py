import unittest
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from models.weather_schemas import (
    MarineForecastSeries, MarineForecastValue, NearshoreForecast, NearshoreGridLocation,
)
from services.waves_service import get_waves_data


class WavesServiceTests(unittest.TestCase):
    def test_expands_nws_intervals_into_seven_day_local_wave_rows(self):
        empty = MarineForecastSeries(unit="s")
        series = MarineForecastSeries(unit="ft", values=[
            MarineForecastValue(
                valid_start=datetime(2026, 10, 23, 3, tzinfo=UTC),
                duration="PT8H", value=3.0,
            ),
        ])
        nearshore = NearshoreForecast(
            source="NWS", timezone="America/New_York", forecast_days=7,
            grid=NearshoreGridLocation(
                office="MFL", x=1, y=2, lat=25, lng=-80,
                distance_km=1, inferred=False,
            ),
            wave_height=series, wave_period=empty, wave_direction=empty,
            primary_swell_height=empty, primary_swell_period=empty,
            primary_swell_direction=empty, secondary_swell_height=empty,
            secondary_swell_period=empty, secondary_swell_direction=empty,
            wind_wave_height=empty, wind_wave_period=empty, wind_wave_direction=empty,
            wind_speed=empty, wind_direction=empty,
        )
        waves = get_waves_data(
            nearshore, ZoneInfo("America/New_York"), date(2026, 10, 23),
            forecast_days=7,
        )
        self.assertEqual(len(waves), 168)
        self.assertEqual(waves.iloc[0]["date"].isoformat(), "2026-10-23T00:00:00-04:00")
        self.assertEqual(waves.iloc[0]["wave_height"], 3.0)
        self.assertEqual(waves.iloc[-1]["date"].date().isoformat(), "2026-10-29")

    def test_unavailable_nearshore_has_no_wave_rows(self):
        self.assertIsNone(get_waves_data(None, ZoneInfo("UTC"), date(2026, 10, 23)))
