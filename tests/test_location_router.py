import unittest
from unittest.mock import patch

from routers.location_router import get_cities_from_location, get_states


class LocationRouteTests(unittest.TestCase):
    stations = [
        {"id": "8723214", "name": "Virginia Key", "state": "FL"},
        {"id": "8724580", "name": "Key West", "state": "FL"},
        {"id": "8638610", "name": "Sewells Point", "state": "VA"},
        {"name": "Missing station id", "state": "FL"},
    ]

    @patch("routers.location_router._get_stations")
    def test_get_cities_returns_station_ids_and_names_for_state(self, get_stations):
        get_stations.return_value = self.stations

        result = get_cities_from_location("fl")

        self.assertEqual(
            result,
            [
                {"id": "8723214", "name": "Virginia Key"},
                {"id": "8724580", "name": "Key West"},
            ],
        )

    @patch("routers.location_router._get_stations")
    def test_get_states_returns_sorted_unique_codes(self, get_stations):
        get_stations.return_value = self.stations

        self.assertEqual(get_states(), ["FL", "VA"])

    def test_fastapi_registers_dropdown_endpoints(self):
        from api import app

        paths = app.openapi()["paths"]

        self.assertIn("/api/states", paths)
        self.assertIn("/api/cities", paths)
        self.assertIn("/forecast/get_forecast", paths)
        self.assertNotIn("/forecast/get_location", paths)


if __name__ == "__main__":
    unittest.main()
