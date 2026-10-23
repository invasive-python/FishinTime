import unittest
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from models.weather_schemas import PressureTrend
from services import forecast_service
from services.city_data_service import get_location_timezone
from services.noaa_station_service import get_station_id


class NOAAStationServiceTests(unittest.TestCase):
    def test_get_location_timezone_uses_geocoded_timezone(self):
        location_timezone = get_location_timezone(
            {"timezone": "America/Los_Angeles"}
        )

        self.assertEqual(
            datetime(2026, 10, 14, 15, tzinfo=UTC)
            .astimezone(location_timezone)
            .strftime("%Y-%m-%d %H:%M"),
            "2026-10-14 08:00",
        )

    @patch("services.noaa_station_service.get_stations")
    def test_finds_station_id_by_city_name_case_insensitively(self, get_stations):
        get_stations.return_value = [
            {"id": "8721164", "name": "New Smyrna Beach", "state": "FL"}
        ]

        self.assertEqual(get_station_id("new smyrna beach"), "8721164")

    @patch(
        "services.forecast_service.waves.get_waves_data",
        return_value=None,
    )
    @patch(
        "services.forecast_service.pressure.get_fishing_pressure_trend",
        return_value=PressureTrend(
            current_pressure_hpa=1012.0,
            pressure_3_hours_ago_hpa=1010.0,
            change_3h_hpa=2.0,
            trend="Rising rapidly",
            outlook="Pressure outlook.",
        ),
    )
    @patch("services.forecast_service.tides.get_tides_from_station_id_and_dates")
    @patch("services.forecast_service.noaa_stations.get_station_id")
    @patch("services.forecast_service.moon.get_moon_phase_from_city_data")
    @patch("services.forecast_service.city_service.get_city_data")
    @patch("services.forecast_service.weather.get_forecast")
    def test_forecast_uses_city_station_id_for_tide_lookup(
        self,
        get_forecast,
        get_city_data,
        get_moon_phase,
        get_station_id,
        get_tides,
        get_pressure,
        get_waves,
    ):
        requested_date = date(2026, 10, 14)
        get_forecast.return_value = SimpleNamespace(
            periods=[
                SimpleNamespace(
                    start_time=datetime(2026, 10, 14, 15, tzinfo=UTC),
                    precipitation_probability=10,
                    temperature=20,
                    wind_speed={"maxValue": 10, "minValue": 5},
                    wind_direction="E",
                    detailed_forecast="Clear.",
                )
            ]
        )
        get_city_data.return_value = {
            "name": "New Smyrna Beach",
            "latitude": 29.0,
            "longitude": -80.9,
            "timezone": "America/New_York",
        }
        get_moon_phase.return_value = {
            "data": {
                "closestphase": {"year": 2026, "month": 10, "day": 20, "phase": "Full Moon"},
                "curphase": "Waxing Crescent",
                "fracillum": "25%",
            }
        }
        get_station_id.return_value = "8721164"
        get_tides.return_value = [{"t": "2026-10-14 06:00", "v": "2.1", "type": "H"}]

        result = forecast_service.serve_forecast(
            "New Smyrna Beach", "FL", requested_date
        )

        get_station_id.assert_called_once_with("New Smyrna Beach")
        get_forecast.assert_called_once_with("New Smyrna Beach", "FL", requested_date)
        get_city_data.assert_called_once_with("New Smyrna Beach", "FL")
        get_tides.assert_called_once_with("8721164", "2026-10-14")
        get_waves.assert_called_once_with(
            29.0,
            -80.9,
            get_location_timezone(get_city_data.return_value),
        )
        get_pressure.assert_called_once_with(29.0, -80.9)
        self.assertEqual(result.city, "New Smyrna Beach")
        self.assertEqual(result.start_time, "2026-10-14 11:00")
        self.assertEqual(result.pressure.change_3h_hpa, 2.0)


if __name__ == "__main__":
    unittest.main()
