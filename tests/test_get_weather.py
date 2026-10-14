import unittest
from datetime import date
from unittest.mock import Mock, patch

import requests

import services.weather_service as weather_service


class WeatherLookupTests(unittest.TestCase):
    def test_geocoder_uses_requested_city_and_returns_first_result(self):
        response = Mock()
        response.json.return_value = {
            "results": [{"name": "Miami", "latitude": 25.76, "longitude": -80.19}]
        }
        with patch("get_weather.requests.get", return_value=response) as get:
            result = weather_service.get_long_lat_from_city("Miami")

        self.assertEqual(result["name"], "Miami")
        self.assertEqual(get.call_args.kwargs["params"]["name"], "Miami")

    @patch(
        "get_weather.get_grid_data",
        return_value={"properties": {"gridX": 10, "gridY": 20, "gridId": "MFL"}},
    )
    @patch("get_weather.requests.get")
    def test_forecast_returns_periods_starting_on_requested_date(self, get, grid):
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

        result = weather_service.get_forecast(
            {"latitude": 25.76, "longitude": -80.19}, date(2026, 10, 6)
        )

        self.assertEqual(
            [period["name"] for period in result], ["Tuesday", "Tuesday Night"]
        )
        grid.assert_called_once_with(25.76, -80.19)

    @patch(
        "get_weather.get_grid_data",
        return_value={"properties": {"gridX": 10, "gridY": 20, "gridId": "MFL"}},
    )
    @patch("get_weather.requests.get")
    def test_forecast_returns_empty_list_when_date_is_unavailable(
        self, get, grid
    ):
        response = Mock()
        response.json.return_value = {
            "properties": {
                "periods": [
                    {
                        "name": "Tuesday",
                        "startTime": "2026-10-06T06:00:00-04:00",
                    }
                ]
            }
        }
        get.return_value = response

        result = weather_service.get_forecast(
            {"latitude": 25.76, "longitude": -80.19}, date(2026, 10, 7)
        )

        self.assertEqual(result, [])
        grid.assert_called_once_with(25.76, -80.19)

    @patch(
        "get_weather.get_grid_data",
        return_value={"properties": {"gridX": 10, "gridY": 20, "gridId": "MFL"}},
    )
    @patch("get_weather.requests.get")
    def test_invalid_forecast_payload_raises_value_error(self, get, grid):
        response = Mock()
        response.json.return_value = {"properties": {}}
        get.return_value = response

        with self.assertRaises(ValueError):
            weather_service.get_forecast(
                {"latitude": 25.76, "longitude": -80.19}, date(2026, 10, 6)
            )
        grid.assert_called_once_with(25.76, -80.19)

    def test_geocoder_propagates_provider_request_errors(self):
        with patch(
            "get_weather.requests.get",
            side_effect=requests.Timeout("provider timed out"),
        ):
            with self.assertRaises(requests.Timeout):
                weather_service.get_long_lat_from_city("Miami")


if __name__ == "__main__":
    unittest.main()
