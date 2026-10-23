import json
import unittest

import pandas as pd

from models.weather_schemas import ForecastResponse, PressureTrend


class ForecastResponseTests(unittest.TestCase):
    def test_waves_dataframe_is_validated_and_serialized_as_records(self):
        waves = pd.DataFrame(
            {
                "date": pd.date_range(
                    "2026-10-23", periods=1, tz="UTC"
                ).tz_convert("America/New_York"),
                "wave_height": [1.2],
            }
        )
        response = ForecastResponse(
            city="Miami",
            date="2026-10-23",
            precipitation_probability=0,
            start_time="2026-10-23 06:00",
            temp=80,
            wind_speed_max=10.0,
            wind_speed_min=5.0,
            wind_direction="E",
            moon_current_phase="Full Moon",
            moon_closest_phase="Full Moon",
            moon_closest_phase_date="2026-10-23",
            moon_brightness="100%",
            predictions=[],
            waves=waves,
            detailed_forecast="Clear",
            pressure=PressureTrend(
                current_pressure_hpa=1012.0,
                pressure_3_hours_ago_hpa=1010.0,
                change_3h_hpa=2.0,
                trend="Rising rapidly",
                outlook="Pressure outlook.",
            ),
        )

        self.assertIs(response.waves, waves)
        self.assertEqual(
            json.loads(response.model_dump_json())["waves"],
            [{"date": "2026-10-22T20:00:00-04:00", "wave_height": 1.2}],
        )
        self.assertEqual(
            json.loads(response.model_dump_json())["pressure"]["change_3h_hpa"],
            2.0,
        )
        self.assertIn("waves", ForecastResponse.model_json_schema()["properties"])


if __name__ == "__main__":
    unittest.main()
