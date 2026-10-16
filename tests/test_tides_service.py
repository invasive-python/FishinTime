import unittest
from unittest.mock import Mock, patch

import requests

from services.tides_service import (
    get_tide_data,
    get_tides_from_station_id_and_dates,
)


class TideServiceTests(unittest.TestCase):
    @patch("services.tides_service.get_tide_data")
    def test_formats_dates_for_noaa_api(self, get_tide_data_mock):
        get_tide_data_mock.return_value = {
            "predictions": [{"t": "2026-10-16 06:00", "v": "2.1", "type": "H"}]
        }

        predictions = get_tides_from_station_id_and_dates("8721164", "2026-10-16")

        self.assertEqual(predictions, get_tide_data_mock.return_value["predictions"])
        get_tide_data_mock.assert_called_once_with("8721164", "20261016", "20261017")

    @patch("services.tides_service.requests.get")
    def test_http_errors_are_propagated(self, get):
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError("NOAA unavailable")
        get.return_value = response

        with self.assertRaises(requests.HTTPError):
            get_tide_data("8721164", "20261016", "20261017")

    @patch("services.tides_service.requests.get")
    def test_noaa_error_payload_is_not_treated_as_missing_predictions(self, get):
        response = Mock()
        response.json.return_value = {"error": {"message": "Invalid station"}}
        get.return_value = response

        with self.assertRaisesRegex(ValueError, "contains an error"):
            get_tide_data("8721164", "20261016", "20261017")


if __name__ == "__main__":
    unittest.main()
