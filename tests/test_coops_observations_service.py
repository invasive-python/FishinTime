import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import requests

from services.coops_observations_service import get_water_temperature


class WaterTemperatureTests(unittest.TestCase):
    @patch("services.coops_observations_service.requests.get")
    def test_selects_latest_observation_and_converts_to_station_local_time(self, get):
        get.return_value.json.return_value = {"data": [
            {"t": "2026-03-08 07:30", "v": "68.5"},
            {"t": "2026-03-08 06:30", "v": "67.8"},
            {"t": "2026-03-08 07:36", "v": ""},
        ]}

        result = get_water_temperature("8724580", ZoneInfo("America/New_York"))

        params = get.call_args.kwargs["params"]
        self.assertEqual(
            (params["date"], params["station"], params["product"], params["units"], params["time_zone"]),
            ("recent", "8724580", "water_temperature", "english", "gmt"),
        )
        self.assertEqual(result.temperature_f, 68.5)
        self.assertEqual(result.observed_at.isoformat(), "2026-03-08T03:30:00-04:00")
        self.assertIsNone(result.error)

    @patch("services.coops_observations_service.requests.get")
    def test_station_without_observations_reports_unavailable(self, get):
        get.return_value.json.return_value = {"error": {"message": "No data was found for this station."}}
        result = get_water_temperature("123", ZoneInfo("UTC"))
        self.assertIsNone(result.temperature_f)
        self.assertIn("No data", result.error)
        get.return_value.json.return_value = {"data": []}
        self.assertIn("No water temperature observations", get_water_temperature("123", ZoneInfo("UTC")).error)

    @patch("services.coops_observations_service.requests.get")
    def test_invalid_or_failed_request_is_reported(self, get):
        get.return_value.json.return_value = {"data": [{"t": "2026-03-08 07:30", "v": "NaN"}]}
        with self.assertLogs("services.coops_observations_service", level="WARNING"):
            result = get_water_temperature("123", ZoneInfo("UTC"))
        self.assertIsNone(result.temperature_f)
        self.assertIn("non-finite", result.error)

        get.side_effect = requests.Timeout("timed out")
        with self.assertLogs("services.coops_observations_service", level="WARNING"):
            result = get_water_temperature("123", ZoneInfo("UTC"))
        self.assertIsNone(result.temperature_f)
        self.assertIn("timed out", result.error)
