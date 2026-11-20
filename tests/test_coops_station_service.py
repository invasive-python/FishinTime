import unittest
from concurrent.futures import Future
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from models.weather_schemas import WaterTemperatureObservation
from services import coops_station_service, forecast_service


class CoopsStationTests(unittest.TestCase):
    @patch("services.coops_station_service._get_cached_json")
    def test_selects_nearest_active_sensors_not_broad_product_names(self, get_json):
        stations = [
            {"id": "near", "name": "Near", "lat": 26.0, "lng": -80.0},
            {"id": "far", "name": "Far", "lat": 26.1, "lng": -80.0},
            {"id": "outside", "name": "Outside", "lat": 27.0, "lng": -80.0},
        ]
        def metadata(url):
            if "stations.json" in url:
                return {"stations": stations}
            if "/near/" in url:
                return {"sensors": [
                    {"name": "Water Temperature", "status": 1},
                    {"name": "Barometric Pressure", "status": 0},
                ]}
            if "/far/" in url:
                return {"sensors": [
                    {"name": "Water Temperature", "status": 1},
                    {"name": "Barometric Pressure", "status": 1},
                ]}
            self.fail(f"Unexpected metadata request: {url}")
        get_json.side_effect = metadata
        result = coops_station_service.find_nearest_coops_station(
            26.0, -80.0, max_water_temp_distance_miles=25,
            max_air_pressure_distance_miles=50,
        )
        self.assertEqual(result["water_temperature"]["nearest"]["station_id"], "near")
        self.assertEqual(result["water_temperature"]["alternatives"][0]["station_id"], "far")
        self.assertEqual(result["air_pressure"]["nearest"]["station_id"], "far")
        self.assertIsNone(result["same_station_for_both_products"])

    @patch("services.coops_station_service._get_cached_json")
    def test_malformed_station_inventory_is_not_treated_as_no_stations(self, get_json):
        get_json.return_value = {"error": "temporarily unavailable"}
        with self.assertRaises(coops_station_service.CoopsAPIError):
            coops_station_service.find_nearest_coops_station(26, -80)

    def test_falls_back_to_nearest_station_with_observations(self):
        stations = Future()
        candidates = [
            {"station_id": "near", "name": "Near", "latitude": 26,
             "longitude": -80, "distance_miles": 1},
            {"station_id": "far", "name": "Far", "latitude": 26.1,
             "longitude": -80, "distance_miles": 7},
        ]
        stations.set_result({"water_temperature": {
            "nearest": candidates[0], "alternatives": candidates[1:],
        }})
        lookup = Mock(side_effect=[
            WaterTemperatureObservation(error="No data"),
            WaterTemperatureObservation(temperature_f=74),
        ])
        result = forecast_service._get_nearby_observation(
            stations, "water_temperature", ZoneInfo("UTC"), lookup,
            WaterTemperatureObservation, lambda value: value.temperature_f is not None,
        )
        self.assertEqual(result.temperature_f, 74)
        self.assertEqual(result.station.station_id, "far")
        self.assertEqual([call.args[0] for call in lookup.call_args_list], ["near", "far"])

    def test_station_lookup_failure_is_reported(self):
        stations = Future()
        stations.set_exception(coops_station_service.CoopsAPIError("metadata down for station 8722956"))
        with self.assertLogs("services.forecast_service", level="WARNING"):
            result = forecast_service._get_nearby_observation(
                stations, "water_temperature", ZoneInfo("UTC"), Mock(),
                WaterTemperatureObservation, lambda value: value.temperature_f is not None,
            )
        self.assertIn("Station lookup unavailable", result.error)
        self.assertNotIn("8722956", result.error)

    def test_station_failure_reports_name_without_exposing_station_id(self):
        stations = Future()
        stations.set_result({"water_temperature": {
            "nearest": {"station_id": "8722956", "name": "South Port Everglades"},
            "alternatives": [],
        }})
        with self.assertLogs("services.forecast_service", level="WARNING"):
            result = forecast_service._get_nearby_observation(
                stations, "water_temperature", ZoneInfo("UTC"),
                Mock(return_value=WaterTemperatureObservation(error="No data for 8722956")),
                WaterTemperatureObservation, lambda value: value.temperature_f is not None,
            )
        self.assertIn("South Port Everglades", result.error)
        self.assertNotIn("8722956", result.error)
