import unittest
from datetime import date
from unittest.mock import Mock, patch

import requests
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient

from api import app
from models.weather_schemas import ForecastPeriod
from routers.forecast_router import get_evaluation_status, get_forecast
from services.weather_service import _map_noaa_period


class ForecastRouteTests(unittest.TestCase):
    @patch(
        "api.get_secret",
        side_effect=["test-api-key", "test-agent-id"],
    )
    def test_startup_reads_secret_once_and_stores_it_on_app(self, get_secret):
        with TestClient(app):
            self.assertEqual(app.state.openai_api_key, "test-api-key")
            self.assertEqual(app.state.openai_agent_id, "test-agent-id")

        self.assertEqual(
            [call.args[0] for call in get_secret.call_args_list],
            ["FishinSecret_OpenAI", "FishinSecret_Agent_Id"],
        )

    def test_maps_nested_temperature(self):
        period = _map_noaa_period(
            {
                "name": "Tuesday",
                "startTime": "2026-10-20T06:00:00-04:00",
                "endTime": "2026-10-20T18:00:00-04:00",
                "temperature": {
                    "unitCode": "wmoUnit:degC",
                    "value": 20,
                },
                "probabilityOfPrecipitation": {"value": 20},
            }
        )

        self.assertIsInstance(period, ForecastPeriod)
        self.assertEqual(period.temperature, 20)
        self.assertEqual(period.temperature_unit, "wmoUnit:degC")
        self.assertEqual(period.precipitation_probability, 20)

    def test_maps_temperature_without_unit(self):
        period = _map_noaa_period(
            {
                "name": "Tuesday",
                "startTime": "2026-10-20T06:00:00-04:00",
                "endTime": "2026-10-20T18:00:00-04:00",
                "temperature": {"value": 20},
            }
        )

        self.assertEqual(period.temperature, 20)
        self.assertIsNone(period.temperature_unit)

    @patch(
        "routers.forecast_router.forecast_service.serve_forecast",
        side_effect=requests.Timeout("provider timed out"),
    )
    def test_provider_failure_is_reported_as_bad_gateway(self, serve_forecast):
        with self.assertRaises(HTTPException) as raised:
            get_forecast(
                request=Mock(),
                background_tasks=BackgroundTasks(),
                city="Miami",
                state="FL",
                date=date.today().isoformat(),
            )

        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("External provider", raised.exception.detail)
        serve_forecast.assert_called_once()

    @patch(
        "routers.forecast_router.forecast_service.serve_forecast",
    )
    def test_forecast_queues_ai_evaluation(self, serve_forecast):
        forecast = Mock()
        forecast.city = "Miami"
        forecast.date = date.today().isoformat()
        forecast.precipitation_probability = 20
        forecast.start_time = "2026-10-19 06:00"
        forecast.temp = 80
        forecast.wind_speed_max = 10
        forecast.wind_speed_min = 5
        forecast.wind_direction = "E"
        forecast.moon_current_phase = "Full Moon"
        forecast.moon_closest_phase_date = "2026-10-20"
        forecast.moon_closest_phase = "New Moon"
        forecast.moon_brightness = "100%"
        forecast.predictions = []
        forecast.detailed_forecast = "Clear"
        forecast.model_dump_json.return_value = "{}"
        serve_forecast.return_value = forecast

        evaluation_jobs = {}
        background_tasks = BackgroundTasks()
        response = get_forecast(
            request=Mock(
                app=Mock(
                    state=Mock(
                        openai_api_key="test-api-key",
                        openai_agent_id="test-agent-id",
                        evaluation_jobs=evaluation_jobs,
                    )
                )
            ),
            background_tasks=background_tasks,
            city="Miami",
            state="FL",
            date=date.today().isoformat(),
        )

        self.assertIs(response, forecast)
        self.assertEqual(forecast.temp, 80)
        self.assertIsNotNone(response.evaluation_id)
        self.assertEqual(evaluation_jobs[response.evaluation_id]["status"], "pending")
        self.assertEqual(len(background_tasks.tasks), 1)
        serve_forecast.assert_called_once()

    def test_evaluation_status_returns_completed_result(self):
        request = Mock(
            app=Mock(
                state=Mock(
                    evaluation_jobs={
                        "job-id": {
                            "status": "completed",
                            "ai_evaluation": "Fish at dawn.",
                        }
                    }
                )
            )
        )

        response = get_evaluation_status("job-id", request)

        self.assertEqual(response.status, "completed")
        self.assertEqual(response.ai_evaluation, "Fish at dawn.")

    def test_evaluation_status_returns_not_found_for_unknown_job(self):
        request = Mock(app=Mock(state=Mock(evaluation_jobs={})))

        with self.assertRaises(HTTPException) as raised:
            get_evaluation_status("missing", request)

        self.assertEqual(raised.exception.status_code, 404)

    def test_openapi_registers_current_forecast_contract(self):
        schema = app.openapi()
        operation = schema["paths"]["/forecast/get_forecast"]["get"]
        parameters = {
            parameter["name"]: parameter for parameter in operation["parameters"]
        }

        self.assertEqual(set(parameters), {"city", "state", "date"})
        self.assertTrue(all(parameter["required"] for parameter in parameters.values()))
        response_reference = operation["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        self.assertEqual(response_reference, "#/components/schemas/ForecastResponse")


if __name__ == "__main__":
    unittest.main()
