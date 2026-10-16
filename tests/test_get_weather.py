import unittest
from datetime import date
from unittest.mock import Mock, patch

import requests

from services.city_data_service import get_long_lat_from_city
from services.weather_service import get_forecast_data


class WeatherLookupTests(unittest.TestCase):
    def test_geocoder_filters_results_by_state(self):
        response = Mock()
        response.json.return_value = {
            "results": [
                {"name": "Miami", "admin1": "Oklahoma"},
                {
                    "name": "Miami",
                    "admin1": "Florida",
                    "latitude": 25.76,
                    "longitude": -80.19,
                },
            ]
        }
        with patch(
            "services.city_data_service.requests.get", return_value=response
        ) as get:
            result = get_long_lat_from_city("Miami", "FL")

        self.assertEqual(result["admin1"], "Florida")
        self.assertEqual(get.call_args.kwargs["params"]["name"], "Miami")
        response.raise_for_status.assert_called_once_with()

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
    def test_invalid_forecast_payload_raises_value_error(self, get, grid):
        response = Mock()
        response.json.return_value = {"properties": {}}
        get.return_value = response

        with self.assertRaises(ValueError):
            get_forecast_data(
                {"latitude": 25.76, "longitude": -80.19}, date(2026, 10, 6)
            )
        grid.assert_called_once_with(25.76, -80.19)

    def test_geocoder_propagates_provider_request_errors(self):
        with patch(
            "services.city_data_service.requests.get",
            side_effect=requests.Timeout("provider timed out"),
        ):
            with self.assertRaises(requests.Timeout):
                get_long_lat_from_city("Miami", "FL")


if __name__ == "__main__":
    unittest.main()
