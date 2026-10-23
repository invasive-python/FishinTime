import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from services.waves_service import get_waves_data


class WavesServiceTests(unittest.TestCase):
    @patch("services.waves_service.openmeteo.weather_api")
    def test_wave_timestamps_are_converted_to_location_timezone(self, weather_api):
        start_timestamp = int(
            datetime(2026, 10, 23, 12, tzinfo=UTC).timestamp()
        )
        variable_values = [[1.0, 1.1], [90, 95], [5, 6], [0.2, 0.3]]
        hourly = SimpleNamespace(
            Variables=lambda index: SimpleNamespace(
                ValuesAsNumpy=lambda: variable_values[index]
            ),
            Time=lambda: start_timestamp,
            TimeEnd=lambda: start_timestamp + 2 * 3600,
            Interval=lambda: 3600,
        )
        weather_api.return_value = [SimpleNamespace(Hourly=lambda: hourly)]

        waves = get_waves_data(25.76, -80.19, ZoneInfo("America/New_York"))

        self.assertEqual(
            [timestamp.isoformat() for timestamp in waves["date"]],
            [
                "2026-10-23T08:00:00-04:00",
                "2026-10-23T09:00:00-04:00",
            ],
        )


if __name__ == "__main__":
    unittest.main()
