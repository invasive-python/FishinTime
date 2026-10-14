import unittest
from datetime import date
from unittest.mock import patch

import requests
from fastapi import HTTPException

from models.weather_schemas import WeatherResponse
from routers.forecast_router import get_forecast


class ForecastRouteTests(unittest.TestCase):
    @patch("routers.get_forecast.weather.get_forecast")
    @patch("routers.get_forecast.weather.get_long_lat_from_city")
    def test_maps_nested_temperature(self, geocode, forecast):
        geocode.return_value = {
            "name": "Miami",
            "latitude": 25.76,
            "longitude": -80.19,
        }
        forecast.return_value = [
            {
                "name": "Tuesday",
                "startTime": "2026-10-06T06:00:00-04:00",
                "endTime": "2026-10-06T18:00:00-04:00",
                "temperature": {
                    "unitCode": "wmoUnit:degC",
                    "value": 31.666666666666668,
                },
            }
        ]

        result = get_forecast(city="Miami", date=date(2026, 10, 6))

        self.assertEqual(result.periods[0].temperature, 31.666666666666668)
        self.assertEqual(result.periods[0].temperature_unit, "wmoUnit:degC")
        forecast.assert_called_once_with(geocode.return_value, date(2026, 10, 6))

    @patch("routers.get_forecast.weather.get_forecast")
    @patch("routers.get_forecast.weather.get_long_lat_from_city")
    def test_maps_nested_temperature_without_unit(self, geocode, forecast):
        geocode.return_value = {
            "name": "Miami",
            "latitude": 25.76,
            "longitude": -80.19,
        }
        forecast.return_value = [
            {
                "name": "Tuesday",
                "startTime": "2026-10-06T06:00:00-04:00",
                "endTime": "2026-10-06T18:00:00-04:00",
                "temperature": {"value": 31.7},
            }
        ]

        result = get_forecast(city="Miami", date=date(2026, 10, 6))

        self.assertEqual(result.periods[0].temperature, 31.7)
        self.assertIsNone(result.periods[0].temperature_unit)
        forecast.assert_called_once_with(geocode.return_value, date(2026, 10, 6))

    @patch("routers.get_forecast.weather.get_forecast")
    @patch("routers.get_forecast.weather.get_long_lat_from_city")
    def test_returns_forecast_for_city_and_date(self, geocode, forecast):
        geocode.return_value = {
            "name": "Miami",
            "latitude": 25.76,
            "longitude": -80.19,
        }
        forecast.return_value = [
            {
                "name": "Tuesday",
                "startTime": "2026-10-06T06:00:00-04:00",
                "endTime": "2026-10-06T18:00:00-04:00",
                "temperature": 84,
                "temperatureUnit": "F",
                "windDirection": "E",
                "probabilityOfPrecipitation": {"value": 20},
                "detailedForecast": "Partly sunny.",
            }
        ]

        result = get_forecast(city="Miami", date=date(2026, 10, 6))

        self.assertIsInstance(result, WeatherResponse)
        self.assertEqual(result.city, "Miami")
        self.assertEqual(result.date, date(2026, 10, 6))
        self.assertEqual(len(result.periods), 1)
        self.assertEqual(result.periods[0].temperature, 84)
        self.assertEqual(result.periods[0].temperature_unit, "F")
        self.assertEqual(result.periods[0].precipitation_probability, 20)
        forecast.assert_called_once_with(geocode.return_value, date(2026, 10, 6))

    @patch("routers.get_forecast.weather.get_long_lat_from_city", return_value=None)
    def test_unknown_city_returns_404(self, geocode):
        with self.assertRaises(HTTPException) as raised:
            get_forecast(city="Not a real place", date=date(2026, 10, 6))

        self.assertEqual(raised.exception.status_code, 404)
        geocode.assert_called_once_with("Not a real place")

    @patch("routers.get_forecast.weather.get_forecast", return_value=[])
    @patch(
        "routers.get_forecast.weather.get_long_lat_from_city",
        return_value={
            "name": "Miami",
            "latitude": 25.76,
            "longitude": -80.19,
        },
    )
    def test_unavailable_date_returns_404(self, geocode, forecast):
        with self.assertRaises(HTTPException) as raised:
            get_forecast(city="Miami", date=date(2026, 10, 20))

        self.assertEqual(raised.exception.status_code, 404)
        geocode.assert_called_once_with("Miami")
        forecast.assert_called_once_with(geocode.return_value, date(2026, 10, 20))

    @patch(
        "routers.get_forecast.weather.get_long_lat_from_city",
        side_effect=requests.Timeout("provider timed out"),
    )
    def test_provider_failure_returns_502(self, geocode):
        with self.assertRaises(HTTPException) as raised:
            get_forecast(city="Miami", date=date(2026, 10, 6))

        self.assertEqual(raised.exception.status_code, 502)
        geocode.assert_called_once_with("Miami")

    @patch(
        "routers.get_forecast.weather.get_forecast",
        return_value=[
            {
                "name": "Tuesday",
                "startTime": "2026-10-06T06:00:00-04:00",
                "endTime": "2026-10-06T18:00:00-04:00",
                "probabilityOfPrecipitation": [],
            }
        ],
    )
    @patch(
        "routers.get_forecast.weather.get_long_lat_from_city",
        return_value={
            "name": "Miami",
            "latitude": 25.76,
            "longitude": -80.19,
        },
    )
    def test_invalid_provider_period_returns_502(self, geocode, forecast):
        with self.assertRaises(HTTPException) as raised:
            get_forecast(city="Miami", date=date(2026, 10, 6))

        self.assertEqual(raised.exception.status_code, 502)
        geocode.assert_called_once_with("Miami")
        forecast.assert_called_once_with(geocode.return_value, date(2026, 10, 6))

    def test_fastapi_openapi_registers_required_query_parameters(self):
        from api import app

        schema = app.openapi()
        operation = schema["paths"]["/forecast/get_forecast"]["get"]
        parameters = {
            parameter["name"]: parameter for parameter in operation["parameters"]
        }
        self.assertEqual(set(parameters), {"city", "date"})
        self.assertTrue(parameters["city"]["required"])
        self.assertTrue(parameters["date"]["required"])
        self.assertEqual(parameters["date"]["schema"]["format"], "date")
        response_reference = operation["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        self.assertEqual(response_reference, "#/components/schemas/WeatherResponse")
        self.assertEqual(
            set(schema["components"]["schemas"]["WeatherResponse"]["properties"]),
            {"city", "date", "periods"},
        )


if __name__ == "__main__":
    unittest.main()
