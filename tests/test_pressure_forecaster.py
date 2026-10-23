import unittest
from unittest.mock import Mock, patch

import requests

from models.weather_schemas import PressureTrend
from services.pressure_forecaster import get_fishing_pressure_trend


class PressureForecasterTests(unittest.TestCase):
    @patch("services.pressure_forecaster.requests.get")
    def test_uses_open_meteo_forecast_api_and_json_response(self, get):
        response = Mock()
        response.json.return_value = {
            "current": {"pressure_msl": 1012.0, "time": "2026-10-23T12:00"},
            "hourly": {
                "time": [
                    "2026-10-23T09:00",
                    "2026-10-23T10:00",
                    "2026-10-23T11:00",
                    "2026-10-23T12:00",
                ],
                "pressure_msl": [1010.0, 1010.5, 1011.0, 1012.0],
            },
        }
        get.return_value = response

        pressure = get_fishing_pressure_trend(26.23, -80.12)

        get.assert_called_once()
        self.assertEqual(
            get.call_args.args[0],
            "https://api.open-meteo.com/v1/forecast",
        )
        self.assertEqual(get.call_args.kwargs["params"]["hourly"], "pressure_msl")
        self.assertEqual(get.call_args.kwargs["timeout"], 20)
        self.assertEqual(
            pressure,
            PressureTrend(
                current_pressure_hpa=1012.0,
                pressure_3_hours_ago_hpa=1010.0,
                change_3h_hpa=2.0,
                trend="Rising rapidly",
                outlook="Poor: rapidly rising pressure may slow fish activity.",
            ),
        )

    @patch("services.pressure_forecaster.requests.get")
    def test_reports_html_response_instead_of_raising_json_decode_error(self, get):
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Type": "text/html"}
        response.text = "<!doctype html><html></html>"
        response.json.side_effect = requests.exceptions.JSONDecodeError(
            "Expecting value", response.text, 0
        )
        get.return_value = response

        error = get_fishing_pressure_trend(26.23, -80.12)

        self.assertIn("Expected JSON but received text/html", error.error)
        self.assertIn("<!doctype html>", error.error)

    @patch("services.pressure_forecaster.requests.get")
    def test_matches_quarter_hour_current_time_to_prior_hourly_readings(self, get):
        response = Mock()
        response.json.return_value = {
            "current": {
                "pressure_msl": 1014.5,
                "time": "2026-10-23T19:45",
            },
            "hourly": {
                "time": [
                    "2026-10-23T16:00",
                    "2026-10-23T17:00",
                    "2026-10-23T18:00",
                    "2026-10-23T19:00",
                    "2026-10-23T20:00",
                ],
                "pressure_msl": [1014.4, 1014.4, 1014.3, 1014.4, 1014.5],
            },
        }
        get.return_value = response

        pressure = get_fishing_pressure_trend(26.23, -80.12)

        self.assertEqual(pressure.current_pressure_hpa, 1014.5)
        self.assertEqual(pressure.pressure_3_hours_ago_hpa, 1014.4)
        self.assertAlmostEqual(pressure.change_3h_hpa, 0.1)
        self.assertEqual(pressure.trend, "Stable")


if __name__ == "__main__":
    unittest.main()
