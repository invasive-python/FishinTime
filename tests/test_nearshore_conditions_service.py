import unittest
from datetime import date
from unittest.mock import patch
from zoneinfo import ZoneInfo

from models.weather_schemas import NearshoreGridLocation
from services.nearshore_conditions_service import (
    _find_nearest_marine_gridpoint,
    _get_grid_location,
    get_nearshore_conditions,
)


class NearshoreConditionsServiceTests(unittest.TestCase):
    @staticmethod
    def _gridpoint(lat, lon, *, marine):
        properties = {}
        if marine:
            values = [
                {"validTime": "2026-10-23T12:00:00+00:00/PT6H", "value": 1.0},
                {"validTime": "2026-10-23T18:00:00+00:00/PT6H", "value": 1.0},
            ]
            properties = {
                "waveHeight": {"values": values},
                "wavePeriod": {"values": values},
            }
        return {
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [lon - 0.001, lat - 0.001],
                    [lon + 0.001, lat - 0.001],
                    [lon + 0.001, lat + 0.001],
                    [lon - 0.001, lat + 0.001],
                    [lon - 0.001, lat - 0.001],
                ]],
            },
            "properties": properties,
        }

    @patch("services.nearshore_conditions_service._is_coastal_gridpoint", return_value=True)
    @patch("services.nearshore_conditions_service._fetch_gridpoint")
    def test_search_selects_nearest_coastal_cell_inside_distance_limit(
        self, fetch_gridpoint, is_coastal
    ):
        marine_cells = {
            (100, 100): self._gridpoint(0.0, 0.0, marine=False),
            (100, 101): self._gridpoint(0.0, 0.01, marine=True),
            (101, 100): self._gridpoint(0.0, 0.02, marine=True),
            (101, 101): self._gridpoint(0.0, 0.04, marine=True),
        }
        fetch_gridpoint.side_effect = lambda office, x, y: marine_cells.get((x, y))

        result = _find_nearest_marine_gridpoint(
            "MFL", 100, 100, 0.0, 0.0, max_distance_km=3.0
        )

        self.assertEqual(result[:2], (100, 101))
        self.assertAlmostEqual(result[2], 0.0)
        self.assertAlmostEqual(result[3], 0.01)
        self.assertLessEqual(result[4], 3.0)
        is_coastal.assert_called()

    @patch("services.nearshore_conditions_service._find_nearest_marine_gridpoint")
    @patch("services.nearshore_conditions_service.get_grid_data")
    def test_inferred_is_true_only_beyond_two_point_five_kilometers(
        self, get_grid_data, find_nearest
    ):
        get_grid_data.return_value = {
            "properties": {"gridId": "MFL", "gridX": 10, "gridY": 20}
        }

        for distance, inferred in ((2.5, False), (2.5001, True)):
            with self.subTest(distance=distance):
                find_nearest.return_value = (11, 20, 25.0, -80.0, distance)

                grid = _get_grid_location(25.0, -80.0, max_distance_km=10.0)

                self.assertEqual(grid.distance_km, distance)
                self.assertEqual(grid.inferred, inferred)

        find_nearest.assert_any_call("MFL", 10, 20, 25.0, -80.0, 10.0)

    @patch("services.nearshore_conditions_service._fetch_gridpoint")
    @patch("services.nearshore_conditions_service._get_grid_location")
    def test_returns_filtered_multi_day_series_with_converted_units(
        self, get_grid_location, fetch_gridpoint
    ):
        get_grid_location.return_value = NearshoreGridLocation(
            office="MFL",
            x=11,
            y=20,
            lat=25.0,
            lng=-80.0,
            distance_km=2.19,
            inferred=False,
        )
        fetch_gridpoint.return_value = {
            "properties": {
                "waveHeight": {
                    "uom": "wmoUnit:m",
                    "values": [
                        {
                            "validTime": "2026-10-23T12:00:00+00:00/PT6H",
                            "value": 1.2,
                        },
                        {
                            "validTime": "2026-10-31T12:00:00+00:00/PT6H",
                            "value": 2.0,
                        },
                    ],
                },
                "wavePeriod": {
                    "uom": "wmoUnit:s",
                    "values": [
                        {
                            "validTime": "2026-10-23T12:00:00+00:00/PT6H",
                            "value": 7,
                        }
                    ],
                },
            }
        }

        result = get_nearshore_conditions(
            25.0,
            -80.0,
            date(2026, 10, 23),
            ZoneInfo("America/New_York"),
            forecast_days=7,
        )

        self.assertEqual(result.source, "NWS forecastGridData")
        self.assertEqual(result.grid.distance_km, 2.19)
        self.assertFalse(result.grid.inferred)
        self.assertEqual(result.wave_height.unit, "ft")
        self.assertAlmostEqual(result.wave_height.values[0].value, 1.2 * 3.28084)
        self.assertEqual(
            result.wave_height.values[0].valid_start.isoformat(),
            "2026-10-23T12:00:00+00:00",
        )
        self.assertEqual(result.wave_period.values[0].value, 7)
        self.assertEqual(result.wave_direction.values, [])
        self.assertEqual(result.forecast_days, 7)
        fetch_gridpoint.assert_called_once_with("MFL", 11, 20)
        get_grid_location.assert_called_once_with(25.0, -80.0, 10.0)

    @patch("services.nearshore_conditions_service._get_grid_location", return_value=None)
    def test_returns_none_when_no_marine_cell_is_within_search_limit(
        self, get_grid_location
    ):
        result = get_nearshore_conditions(
            25.0,
            -80.0,
            date(2026, 10, 23),
            ZoneInfo("America/New_York"),
        )

        self.assertIsNone(result)
        get_grid_location.assert_called_once_with(25.0, -80.0, 10.0)


if __name__ == "__main__":
    unittest.main()
