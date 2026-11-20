import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import requests

from services.pressure_forecaster import get_fishing_pressure_trend


class PressureForecasterTests(unittest.TestCase):
    @patch("services.coops_observations_service.requests.get")
    def test_uses_noaa_station_observations_and_converts_millibars(self, get):
        get.return_value.json.return_value = {"data": [
            {"t": "2026-10-23 09:00", "v": "1009.0"},
            {"t": "2026-10-23 12:00", "v": "1011.0"},
        ]}

        result = get_fishing_pressure_trend("8723214", ZoneInfo("America/New_York"))

        self.assertEqual(get.call_args.kwargs["params"]["product"], "air_pressure")
        self.assertEqual(get.call_args.kwargs["params"]["station"], "8723214")
        self.assertEqual(get.call_args.kwargs["params"]["units"], "english")
        self.assertEqual(get.call_args.kwargs["params"]["time_zone"], "gmt")
        self.assertEqual(result.source, "NOAA CO-OPS")
        self.assertEqual(result.observed_at.isoformat(), "2026-10-23T08:00:00-04:00")
        self.assertAlmostEqual(result.current_pressure_inhg, 1011 / 33.8638866667)
        self.assertAlmostEqual(result.change_3h_inhg, 2 / 33.8638866667)
        self.assertEqual(result.trend, "Rising rapidly")

    @patch("services.coops_observations_service.requests.get")
    def test_no_sensor_data_is_reported_as_unavailable(self, get):
        get.return_value.json.return_value = {
            "error": {"message": "No data was found for this station."}
        }
        result = get_fishing_pressure_trend("123", ZoneInfo("UTC"))
        self.assertIsNone(result.current_pressure_inhg)
        self.assertIn("No data", result.error)

    @patch("services.coops_observations_service.requests.get")
    def test_missing_three_hour_observation_does_not_invent_trend(self, get):
        get.return_value.json.return_value = {"data": [
            {"t": "2026-10-23 12:00", "v": "1011.0"},
        ]}
        result = get_fishing_pressure_trend("123", ZoneInfo("UTC"))
        self.assertIsNotNone(result.current_pressure_inhg)
        self.assertIsNone(result.trend)
        self.assertIn("three hours", result.error)

    @patch("services.coops_observations_service.requests.get")
    def test_fetches_missing_history_at_exact_utc_interval(self, get):
        recent = Mock()
        recent.json.return_value = {"data": [
            {"t": "2026-03-08 08:00", "v": "1011.0"},
        ]}
        history = Mock()
        history.json.return_value = {"data": [
            {"t": "2026-03-08 04:54", "v": "1012.0"},
            {"t": "2026-03-08 05:00", "v": "1012.2"},
        ]}
        get.side_effect = [recent, history]

        result = get_fishing_pressure_trend("8722956", ZoneInfo("America/New_York"))

        self.assertEqual(result.observed_at.isoformat(), "2026-03-08T04:00:00-04:00")
        self.assertAlmostEqual(result.pressure_3_hours_ago_inhg, 1012.2 / 33.8638866667)
        self.assertAlmostEqual(result.change_3h_inhg, -1.2 / 33.8638866667)
        self.assertEqual(result.trend, "Falling rapidly")
        self.assertIsNone(result.error)
        params = get.call_args_list[1].kwargs["params"]
        self.assertEqual(params["station"], "8722956")
        self.assertEqual(params["product"], "air_pressure")
        self.assertEqual(params["time_zone"], "gmt")
        self.assertEqual(params["begin_date"], "20260308 04:48")
        self.assertEqual(params["end_date"], "20260308 05:00")

    @patch("services.coops_observations_service.requests.get")
    def test_failed_history_lookup_preserves_current_pressure_and_reports_error(self, get):
        recent = Mock()
        recent.json.return_value = {"data": [{"t": "2026-10-23 12:00", "v": "1011.0"}]}
        get.side_effect = [recent, requests.Timeout("timed out")]
        with self.assertLogs("services.pressure_forecaster", level="WARNING"):
            result = get_fishing_pressure_trend("123", ZoneInfo("UTC"))
        self.assertIsNotNone(result.current_pressure_inhg)
        self.assertIsNone(result.trend)
        self.assertIn("Pressure history lookup failed", result.error)
