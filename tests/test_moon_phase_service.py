import unittest
from datetime import date
from unittest.mock import Mock, patch

import requests

from services.moon_phase_service import (
    get_moon_phase_data,
    get_moon_phase_from_city_data,
)


class MoonPhaseServiceTests(unittest.TestCase):
    @patch("services.moon_phase_service.requests.get")
    def test_http_errors_are_propagated(self, get):
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError(
            "USNO unavailable"
        )
        get.return_value = response

        with self.assertRaises(requests.HTTPError):
            get_moon_phase_data("2026-10-16", (25.76, -80.19))

    @patch("services.moon_phase_service.get_moon_phase_data")
    def test_utc_offset_is_derived_from_the_station_timezone_and_date(self, get_data):
        get_data.return_value = {"properties": {"data": {}}}
        coords = (34.0, -118.0)
        for timezone_name, day, expected in (
            ("America/New_York", date(2026, 11, 22), -5.0),
            ("America/New_York", date(2026, 7, 4), -4.0),
            ("America/Los_Angeles", date(2026, 11, 22), -8.0),
            ("Pacific/Honolulu", date(2026, 7, 4), -10.0),
        ):
            get_moon_phase_from_city_data(
                {"latitude": 34.0, "longitude": -118.0, "timezone": timezone_name}, day
            )
            get_data.assert_called_with(day, coords, expected)

        get_moon_phase_from_city_data({"latitude": 34.0, "longitude": -118.0}, "2026-10-16")
        get_data.assert_called_with("2026-10-16", coords, None)

    @patch("services.moon_phase_service.requests.get")
    def test_offset_is_sent_to_usno_only_when_known(self, get):
        get.return_value.json.return_value = {"properties": {}}
        get_moon_phase_data("2026-11-22", (26.19, -80.09), -5.0)
        self.assertEqual(get.call_args.kwargs["params"]["tz"], -5.0)
        get_moon_phase_data("2026-11-22", (26.19, -80.09))
        self.assertNotIn("tz", get.call_args.kwargs["params"])

    @patch("services.moon_phase_service.get_moon_phase_data")
    def test_invalid_provider_payload_raises_value_error(self, get_data):
        get_data.return_value = {}

        with self.assertRaisesRegex(ValueError, "missing its properties"):
            get_moon_phase_from_city_data(
                {"latitude": 25.76, "longitude": -80.19},
                "2026-10-16",
            )


if __name__ == "__main__":
    unittest.main()
