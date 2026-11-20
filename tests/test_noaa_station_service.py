import unittest
from datetime import UTC, date, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from models.station import Station
from models.weather_schemas import (
    ActiveAlerts,
    ForecastPeriod,
    PrecipitationCondition,
    PrecipitationInterval,
    PressureTrend,
    WaterTemperatureObservation,
    WeatherAlert,
)
from services import forecast_service
from services.city_data_service import get_location_timezone
from services.noaa_station_service import (
    AmbiguousStationError,
    get_station,
    get_station_id,
    get_stations,
)


class NOAAStationServiceTests(unittest.TestCase):
    def test_precipitation_time_respects_local_day_and_daylight_saving(self):
        condition = PrecipitationCondition(weather="rain", coverage="chance")
        intervals = [
            PrecipitationInterval(
                start_time=datetime(2026, 3, 9, 4, tzinfo=UTC),
                end_time=datetime(2026, 3, 9, 5, tzinfo=UTC),
                conditions=[condition],
            ),
            PrecipitationInterval(
                start_time=datetime(2026, 3, 8, 6, 30, tzinfo=UTC),
                end_time=datetime(2026, 3, 8, 8, tzinfo=UTC),
                conditions=[condition],
            ),
        ]
        daily = forecast_service._daily_forecast(
            date(2026, 3, 8), None, {}, None, ZoneInfo("America/New_York"), intervals
        )
        self.assertEqual(daily.start_time, "2026-03-08 01:30")
        next_day = forecast_service._daily_forecast(
            date(2026, 3, 9), None, {}, None, ZoneInfo("America/New_York"), intervals
        )
        self.assertEqual(next_day.start_time, "2026-03-09 00:00")

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
        "services.forecast_service.nws_alerts.get_active_alerts",
        return_value=ActiveAlerts(
            timezone="America/New_York",
            items=[WeatherAlert(event="Small Craft Advisory", severity="Minor")],
        ),
    )
    @patch(
        "services.forecast_service.waves.get_waves_data",
        return_value=None,
    )
    @patch(
        "services.forecast_service.pressure.get_fishing_pressure_trend",
        return_value=PressureTrend(
            source="NOAA CO-OPS",
            observed_at=datetime(2026, 10, 14, 14, tzinfo=UTC),
            current_pressure_inhg=29.88,
            pressure_3_hours_ago_inhg=29.82,
            change_3h_inhg=0.06,
            trend="Rising rapidly",
            outlook="Pressure outlook.",
        ),
    )
    @patch(
        "services.forecast_service.coops_stations.find_nearest_coops_station",
        return_value={
            "air_pressure": {"nearest": {
                "station_id": "pressure", "name": "Pressure station",
                "latitude": 29.0, "longitude": -81.0, "distance_miles": 5.0,
            }, "alternatives": []},
            "water_temperature": {"nearest": {
                "station_id": "water", "name": "Water station",
                "latitude": 29.1, "longitude": -81.1, "distance_miles": 3.0,
            }, "alternatives": []},
        },
    )
    @patch(
        "services.forecast_service.coops.get_water_temperature",
        return_value=WaterTemperatureObservation(
            observed_at=datetime(2026, 10, 14, 14, tzinfo=UTC),
            temperature_f=75.2,
        ),
    )
    @patch("services.forecast_service.nearshore.get_nearshore_conditions", return_value=None)
    @patch("services.forecast_service.tides.get_tides_for_date_range")
    @patch("services.forecast_service.noaa_stations.get_station")
    @patch("services.forecast_service.moon.get_moon_phase_from_city_data")
    @patch("services.forecast_service.weather.get_forecast")
    def test_forecast_uses_city_station_id_for_tide_lookup(
        self,
        get_forecast,
        get_moon_phase,
        get_station,
        get_tides,
        get_nearshore,
        get_water_temperature,
        get_observation_stations,
        get_pressure,
        get_waves,
        get_alerts,
    ):
        requested_date = date(2026, 10, 14)
        get_forecast.return_value = SimpleNamespace(
            timezone="America/New_York",
            periods=[
                ForecastPeriod(
                    name="Tuesday",
                    start_time=datetime(2026, 10, 14, 15, tzinfo=UTC),
                    end_time=datetime(2026, 10, 15, 3, tzinfo=UTC),
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
            ],
            precipitation_intervals=[
                PrecipitationInterval(
                    start_time=datetime(2026, 10, 14, 17, tzinfo=UTC),
                    end_time=datetime(2026, 10, 15, 6, tzinfo=UTC),
                    conditions=[PrecipitationCondition(weather="rain", coverage="chance")],
                ),
            ],
        )
        get_station.return_value = Station(
            id="8721164", name="New Smyrna Beach", lat=29.1234,
            lng=-80.9876, state="FL", county="Volusia County"
        )
        get_moon_phase.side_effect = lambda city_data, day: {
            "data": {
                "closestphase": {"year": 2026, "month": 10, "day": 20, "phase": "Full Moon"},
                "curphase": "Waxing Crescent",
                "fracillum": f"{day.day}%",
                "sundata": [
                    {"phen": "Rise", "time": "07:01"}, {"phen": "Set", "time": "18:12"},
                ],
                "moondata": [{"phen": "Rise", "time": "13:20"}],
            }
        }
        get_tides.return_value = [{"t": "2026-10-14 06:00", "v": "2.1", "type": "H"}]
        weather_and_tides = Barrier(2, timeout=5)
        dependent_requests = Barrier(3, timeout=5)
        weather_result = get_forecast.return_value
        tide_result = get_tides.return_value
        pressure_result = get_pressure.return_value
        moon_result = get_moon_phase.side_effect

        def weather_lookup(*_args, **_kwargs):
            weather_and_tides.wait()
            return weather_result

        def tide_lookup(*_args, **_kwargs):
            weather_and_tides.wait()
            return tide_result

        def nearshore_lookup(*_args, **_kwargs):
            dependent_requests.wait()
            return None

        def pressure_lookup(*_args, **_kwargs):
            dependent_requests.wait()
            return pressure_result

        def moon_lookup(city_data, day):
            if day == date(2026, 10, 11):
                dependent_requests.wait()
            return moon_result(city_data, day)

        get_forecast.side_effect = weather_lookup
        get_tides.side_effect = tide_lookup
        get_nearshore.side_effect = nearshore_lookup
        get_pressure.side_effect = pressure_lookup
        get_moon_phase.side_effect = moon_lookup

        window_start = date(2026, 10, 11)
        result = forecast_service.serve_forecast(
            "New Smyrna Beach", "FL", requested_date, "8721164", start_date=window_start
        )

        get_station.assert_called_once_with("New Smyrna Beach", "FL", "8721164")
        get_forecast.assert_called_once_with(
            29.1234, -80.9876, window_start, forecast_days=7, allow_empty=True
        )
        city_data = {
            "latitude": 29.1234,
            "longitude": -80.9876,
            "timezone": "America/New_York",
        }
        self.assertEqual(get_moon_phase.call_count, 7)
        self.assertEqual(
            {call.args[1] for call in get_moon_phase.call_args_list},
            {window_start + timedelta(days=offset) for offset in range(7)},
        )
        get_tides.assert_called_once_with("8721164", window_start, 7)
        get_nearshore.assert_called_once_with(
            29.1234,
            -80.9876,
            window_start,
            get_location_timezone(city_data),
            forecast_days=7,
        )
        get_waves.assert_called_once_with(
            None,
            get_location_timezone(city_data),
            window_start,
            forecast_days=7,
        )
        get_observation_stations.assert_called_once_with(29.1234, -80.9876)
        get_pressure.assert_called_once_with("pressure", get_location_timezone(city_data))
        get_water_temperature.assert_called_once_with("water", get_location_timezone(city_data))
        get_alerts.assert_called_once_with(
            [(29.1234, -80.9876)], "FL", "Volusia County", "America/New_York"
        )
        self.assertEqual(result.timezone, "America/New_York")
        self.assertEqual(result.alerts.items[0].event, "Small Craft Advisory")
        first_day = result.daily_forecasts[0]
        self.assertEqual(
            (first_day.sunrise, first_day.sunset, first_day.moonrise, first_day.moonset),
            ("07:01", "18:12", "13:20", None),
        )
        self.assertEqual(result.city, "New Smyrna Beach")
        self.assertEqual(result.city_lat, "29.1234")
        self.assertEqual(result.city_long, "-80.9876")
        self.assertEqual(result.start_time, "2026-10-14 13:00")
        self.assertEqual(result.temp, 68)
        self.assertEqual(result.water_temperature.temperature_f, 75.2)
        self.assertEqual(result.water_temperature.station.station_id, "water")
        self.assertEqual(result.model_dump(mode="json")["water_temperature"]["observed_at"],
                         "2026-10-14T14:00:00Z")
        self.assertEqual(result.wind_speed_max, 6.21)
        self.assertEqual(result.wind_speed_min, 3.11)
        self.assertEqual(result.pressure.change_3h_inhg, 0.06)
        self.assertEqual(result.pressure.station.station_id, "pressure")
        self.assertEqual(result.station.id, "8721164")
        self.assertEqual(result.station.county, "Volusia County")
        self.assertEqual(result.weather_forecast, get_forecast.return_value.periods)
        self.assertEqual(result.precipitation_forecast, get_forecast.return_value.precipitation_intervals)
        self.assertEqual(result.forecast_start_date, window_start)
        self.assertEqual(len(result.daily_forecasts), 7)
        self.assertEqual(
            [entry.moon_brightness for entry in result.daily_forecasts],
            ["11%", "12%", "13%", "14%", "15%", "16%", "17%"],
        )
        self.assertEqual(result.daily_forecasts[3].temp, 68)
        self.assertEqual(result.daily_forecasts[4].start_time, "2026-10-15 00:00")
        self.assertIsNone(result.daily_forecasts[5].start_time)
        self.assertEqual(result.daily_forecasts[3].pressure.current_pressure_inhg, 29.88)
        self.assertIsNone(result.daily_forecasts[0].temp)
        self.assertIsNone(result.daily_forecasts[0].pressure.current_pressure_inhg)


if __name__ == "__main__":
    unittest.main()
