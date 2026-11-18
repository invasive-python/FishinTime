import unittest
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from models.station import Station
from models.weather_schemas import PressureTrend
from services import forecast_service
from services.city_data_service import get_location_timezone
from services.noaa_station_service import (
    AmbiguousStationError,
    get_station,
    get_station_id,
    get_stations,
)


class NOAAStationServiceTests(unittest.TestCase):
    @patch("services.noaa_station_service.requests.get")
    def test_get_stations_sorts_by_latitude_then_longitude(self, get):
        response = get.return_value
        response.json.return_value = {
            "stations": [
                {"id": "west", "lat": 29.0, "lng": -81.0},
                {"id": "north", "lat": 30.0, "lng": -80.0},
                {"id": "east", "lat": 29.0, "lng": -80.0},
                None,
            ]
        }

        stations = get_stations()

        self.assertEqual(
            [station["id"] for station in stations], ["west", "east", "north"]
        )

    def test_get_location_timezone_uses_geocoded_timezone(self):
        location_timezone = get_location_timezone(
            {"timezone": "America/Los_Angeles"}
        )

        self.assertEqual(
            datetime(2026, 10, 14, 15, tzinfo=UTC)
            .astimezone(location_timezone)
            .strftime("%Y-%m-%d %H:%M"),
            "2026-10-14 08:00",
        )

    @patch("services.noaa_station_service.get_stations")
    def test_finds_station_id_by_city_name_case_insensitively(self, get_stations):
        get_stations.return_value = [
            {"id": "8721164", "name": "New Smyrna Beach", "state": "FL"}
        ]

        self.assertEqual(get_station_id("new smyrna beach"), "8721164")

    @patch("services.noaa_station_service.get_station_county", return_value="Broward County")
    @patch("services.noaa_station_service.get_stations")
    def test_selects_station_by_id_or_unambiguous_name(self, get_stations, get_county):
        get_stations.return_value = [
            {"id": "1", "name": "Same Name", "state": "FL", "lat": 26.1234, "lng": -80.1234},
            {"id": "2", "name": "Same Name", "state": "FL", "lat": 26.5678, "lng": -80.5678},
            {"id": "3", "name": "Other", "state": "GA", "lat": 31.0, "lng": -81.0},
        ]
        station = get_station("Same Name", "fl", "2")
        self.assertEqual(station.id, "2")
        self.assertEqual(station.lat, 26.5678)
        self.assertEqual(station.county, "Broward County")
        self.assertEqual(get_station("other", "ga").id, "3")
        self.assertIsNone(get_station("Same Name", "GA", "2"))
        with self.assertRaises(AmbiguousStationError):
            get_station("same name", "FL")

    @patch("services.noaa_station_service.get_stations")
    def test_selected_station_with_invalid_coordinates_is_rejected(self, get_stations):
        get_stations.return_value = [
            {"id": "1", "name": "Bad", "state": "FL", "lat": 91.0, "lng": -80.0}
        ]
        with self.assertRaisesRegex(ValueError, "Invalid NOAA station data"):
            get_station("Bad", "FL")

    @patch(
        "services.forecast_service.waves.get_waves_data",
        return_value=None,
    )
    @patch(
        "services.forecast_service.pressure.get_fishing_pressure_trend",
        return_value=PressureTrend(
            current_pressure_inhg=29.88,
            pressure_3_hours_ago_inhg=29.82,
            change_3h_inhg=0.06,
            trend="Rising rapidly",
            outlook="Pressure outlook.",
        ),
    )
    @patch("services.forecast_service.tides.get_tides_from_station_id_and_dates")
    @patch("services.forecast_service.noaa_stations.get_station")
    @patch("services.forecast_service.moon.get_moon_phase_from_city_data")
    @patch("services.forecast_service.weather.get_forecast")
    def test_forecast_uses_city_station_id_for_tide_lookup(
        self,
        get_forecast,
        get_moon_phase,
        get_station,
        get_tides,
        get_pressure,
        get_waves,
    ):
        requested_date = date(2026, 10, 14)
        get_forecast.return_value = SimpleNamespace(
            timezone="America/New_York",
            periods=[
                SimpleNamespace(
                    start_time=datetime(2026, 10, 14, 15, tzinfo=UTC),
                    precipitation_probability=10,
                    temperature=20,
                    temperature_unit="wmoUnit:degC",
                    wind_speed={
                        "maxValue": 10,
                        "minValue": 5,
                        "unitCode": "wmoUnit:km_h-1",
                    },
                    wind_direction="E",
                    detailed_forecast="Clear.",
                )
            ]
        )
        get_station.return_value = Station(
            id="8721164", name="New Smyrna Beach", lat=29.1234,
            lng=-80.9876, state="FL", county="Volusia County"
        )
        get_moon_phase.return_value = {
            "data": {
                "closestphase": {"year": 2026, "month": 10, "day": 20, "phase": "Full Moon"},
                "curphase": "Waxing Crescent",
                "fracillum": "25%",
            }
        }
        get_tides.return_value = [{"t": "2026-10-14 06:00", "v": "2.1", "type": "H"}]

        result = forecast_service.serve_forecast(
            "New Smyrna Beach", "FL", requested_date, "8721164"
        )

        get_station.assert_called_once_with("New Smyrna Beach", "FL", "8721164")
        get_forecast.assert_called_once_with(29.1234, -80.9876, requested_date)
        city_data = {
            "latitude": 29.1234,
            "longitude": -80.9876,
            "timezone": "America/New_York",
        }
        get_moon_phase.assert_called_once_with(city_data, requested_date)
        get_tides.assert_called_once_with("8721164", "2026-10-14")
        get_waves.assert_called_once_with(
            29.1234,
            -80.9876,
            get_location_timezone(city_data),
            requested_date,
        )
        get_pressure.assert_called_once_with(29.1234, -80.9876)
        self.assertEqual(result.city, "New Smyrna Beach")
        self.assertEqual(result.city_lat, "29.1234")
        self.assertEqual(result.city_long, "-80.9876")
        self.assertEqual(result.start_time, "2026-10-14 11:00")
        self.assertEqual(result.temp, 68)
        self.assertEqual(result.wind_speed_max, 6.21)
        self.assertEqual(result.wind_speed_min, 3.11)
        self.assertEqual(result.pressure.change_3h_inhg, 0.06)


if __name__ == "__main__":
    unittest.main()
