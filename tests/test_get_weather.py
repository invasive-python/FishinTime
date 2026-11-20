import unittest
from datetime import date
from unittest.mock import Mock, patch

from fastapi import HTTPException

from services.weather_service import (
    get_forecast,
    get_forecast_data,
    get_precipitation_intervals,
)


class WeatherLookupTests(unittest.TestCase):
    @patch("services.weather_service.requests.get")
    @patch("services.weather_service.get_grid_data")
    def test_forecast_uses_station_coordinates_and_grid_timezone(self, get_grid, get):
        get_grid.return_value = {
            "properties": {
                "gridX": 10, "gridY": 20, "gridId": "MFL", "timeZone": "America/New_York",
                "forecastGridData": "https://api.weather.gov/gridpoints/MFL/10,20",
            }
        }
        forecast_response = Mock()
        forecast_response.json.return_value = {
            "properties": {
                "periods": [{
                    "name": "Tuesday",
                    "startTime": "2026-10-06T06:00:00-04:00",
                    "endTime": "2026-10-06T18:00:00-04:00",
                }]
            }
        }
        grid_response = Mock()
        grid_response.json.return_value = {"properties": {"weather": {"values": []}}}
        get.side_effect = [forecast_response, grid_response]
        result = get_forecast(26.118299, -80.144997, date(2026, 10, 6))
        get_grid.assert_called_once_with(26.118299, -80.144997)
        self.assertEqual(result.timezone, "America/New_York")
        self.assertEqual(result.periods[0].name, "Tuesday")
        self.assertIn("/MFL/10,20/forecast", get.call_args_list[0].args[0])
        self.assertEqual(get.call_args_list[1].args[0], "https://api.weather.gov/gridpoints/MFL/10,20")

    @patch("services.weather_service.requests.get")
    def test_grid_intervals_include_precipitation_not_fog_or_dry_thunder(self, get):
        get.return_value.json.return_value = {"properties": {"weather": {"values": [
            {"validTime": "2026-10-13T23:00:00Z/PT3H", "value": [
                {"weather": "fog", "coverage": "patchy"},
            ]},
            {"validTime": "2026-10-14T08:00:00Z/PT2H", "value": [
                {"weather": "thunderstorms", "coverage": "chance", "attributes": ["dry_thunderstorms"]},
                {"weather": "rain_showers", "coverage": "slight_chance"},
            ]},
            {"validTime": "2026-10-14T10:00:00Z/PT1H", "value": None},
            {"validTime": "2026-10-14T11:00:00Z/PT1H", "value": []},
            {"validTime": "2026-10-14T12:00:00Z/PT1H", "value": [
                {"weather": "thunderstorms", "coverage": "chance", "attributes": ["heavy_rain"]},
            ]},
        ]}}}
        intervals = get_precipitation_intervals(
            "https://api.weather.gov/gridpoints/MFL/10,20",
            date(2026, 10, 14), 1, "America/New_York",
        )
        self.assertEqual(len(intervals), 2)
        self.assertEqual(intervals[0].start_time.isoformat(), "2026-10-14T08:00:00+00:00")
        self.assertEqual(intervals[0].conditions[0].weather, "rain_showers")
        self.assertEqual(intervals[0].conditions[0].coverage, "slight_chance")
        self.assertEqual(intervals[1].conditions[0].weather, "thunderstorms")

    @patch("services.weather_service.requests.get")
    def test_invalid_weather_grid_is_reported(self, get):
        get.return_value.json.return_value = {"properties": {"weather": {"values": [
            {"validTime": "invalid", "value": []},
        ]}}}
        with self.assertRaisesRegex(ValueError, "valid-time"):
            get_precipitation_intervals(
                "https://api.weather.gov/gridpoints/MFL/10,20",
                date(2026, 10, 14), 1, "America/New_York",
            )

    @patch("services.weather_service.get_grid_data", return_value={"properties": {}})
    def test_forecast_reports_missing_grid_timezone(self, get_grid):
        with self.assertRaises(HTTPException) as raised:
            get_forecast(26.1, -80.1, date(2026, 10, 6))
        self.assertEqual(raised.exception.status_code, 502)
        get_grid.assert_called_once_with(26.1, -80.1)

    @patch(
        "services.weather_service.get_grid_data",
        return_value={"properties": {"gridX": 10, "gridY": 20, "gridId": "MFL"}},
    )
    @patch("services.weather_service.requests.get")
    def test_forecast_data_only_returns_periods_on_requested_date(
        self, get, grid
    ):
        response = Mock()
        response.json.return_value = {
            "properties": {
                "periods": [
                    {
                        "name": "Tuesday",
                        "startTime": "2026-10-06T06:00:00-04:00",
                    },
                    {
                        "name": "Tuesday Night",
                        "startTime": "2026-10-06T18:00:00-04:00",
                    },
                    {
                        "name": "Wednesday",
                        "startTime": "2026-10-07T06:00:00-04:00",
                    },
                ]
            }
        }
        get.return_value = response

        result = get_forecast_data(
            {"latitude": 25.76, "longitude": -80.19}, date(2026, 10, 6)
        )

        self.assertEqual(
            [period["name"] for period in result], ["Tuesday", "Tuesday Night"]
        )
        grid.assert_called_once_with(25.76, -80.19)
        response.raise_for_status.assert_called_once_with()

    @patch(
        "services.weather_service.get_grid_data",
        return_value={"properties": {"gridX": 10, "gridY": 20, "gridId": "MFL"}},
    )
    @patch("services.weather_service.requests.get")
    def test_forecast_data_includes_the_requested_multi_day_horizon(self, get, grid):
        response = Mock()
        response.json.return_value = {
            "properties": {
                "periods": [
                    {"name": "Tuesday", "startTime": "2026-10-06T06:00:00-04:00"},
                    {"name": "Tuesday Night", "startTime": "2026-10-06T18:00:00-04:00"},
                    {"name": "Wednesday", "startTime": "2026-10-07T06:00:00-04:00"},
                    {"name": "Monday", "startTime": "2026-10-13T06:00:00-04:00"},
                ]
            }
        }
        get.return_value = response

        result = get_forecast_data(
            {"latitude": 25.76, "longitude": -80.19},
            date(2026, 10, 6),
            forecast_days=7,
        )

        self.assertEqual(
            [period["name"] for period in result],
            ["Tuesday", "Tuesday Night", "Wednesday"],
        )
        grid.assert_called_once_with(25.76, -80.19)

    def test_forecast_data_rejects_horizons_over_seven_days(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 7"):
            get_forecast_data(
                {"latitude": 25.76, "longitude": -80.19},
                date(2026, 10, 6),
                forecast_days=8,
            )

    @patch(
        "services.weather_service.get_grid_data",
        return_value={"properties": {"gridX": 10, "gridY": 20, "gridId": "MFL"}},
    )
    @patch("services.weather_service.requests.get")
    def test_invalid_forecast_payload_raises_value_error(self, get, grid):
        response = Mock()
        response.json.return_value = {"properties": {}}
        get.return_value = response

        with self.assertRaises(ValueError):
            get_forecast_data(
                {"latitude": 25.76, "longitude": -80.19}, date(2026, 10, 6)
            )
        grid.assert_called_once_with(25.76, -80.19)


if __name__ == "__main__":
    unittest.main()
