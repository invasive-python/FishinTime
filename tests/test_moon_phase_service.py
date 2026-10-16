import unittest
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
    def test_invalid_provider_payload_raises_value_error(self, get_data):
        get_data.return_value = {}

        with self.assertRaisesRegex(ValueError, "missing its properties"):
            get_moon_phase_from_city_data(
                {"latitude": 25.76, "longitude": -80.19},
                "2026-10-16",
            )


if __name__ == "__main__":
    unittest.main()
