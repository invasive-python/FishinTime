import unittest
from datetime import date
from unittest.mock import Mock, patch

import requests
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient

from api import app
from models.weather_schemas import ForecastPeriod
from routers.forecast_router import (
    get_evaluation,
    get_evaluation_status,
    get_forecast,
)
from services.weather_service import _map_noaa_period


class ForecastRouteTests(unittest.TestCase):
    @patch(
        "api.get_secret",
        side_effect=[
            "test-api-key",
            "test-agent-id",
            "test-stripe-key",
        ],
    )
    def test_billing_pages_and_public_config_are_served(self, get_secret):
        with TestClient(app) as client:
            root = client.get("/")
            page = client.get("/billing/subscribe")
            account_page = client.get("/billing/account")
            client_script = client.get("/billing/client.js")
            config = client.get("/static/config.js")
            stylesheet = client.get("/static/common.css")
            success = client.get("/billing/success")
            cancel = client.get("/billing/cancel")

        self.assertEqual(root.status_code, 200)
        self.assertIn("Find your fishing window", root.text)
        self.assertEqual(page.status_code, 200)
        self.assertIn("Unlock AI fishing recommendations", page.text)
        self.assertIn('data-plan="monthly">Choose monthly</button>', page.text)
        self.assertIn('data-plan="annual">Choose annual</button>', page.text)
        self.assertEqual(account_page.status_code, 200)
        self.assertIn("Sign in and manage your account", account_page.text)
        self.assertIn("Change password", account_page.text)
        self.assertEqual(client_script.status_code, 200)
        self.assertIn("oauth2/authorize", client_script.text)
        self.assertEqual(config.status_code, 200)
        self.assertEqual(stylesheet.status_code, 200)
        self.assertIn("background-image", stylesheet.text)
        self.assertEqual(success.status_code, 200)
        self.assertEqual(cancel.status_code, 200)
        self.assertEqual(get_secret.call_count, 3)

    @patch(
        "api.get_secret",
        side_effect=[
            "test-api-key",
            "test-agent-id",
            "test-stripe-key",
        ],
    )
    def test_static_diagram_is_served(self, get_secret):
        with TestClient(app) as client:
            response = client.get("/static/mermaid-diagram.png")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertTrue(response.content)

    @patch(
        "api.get_secret",
        side_effect=[
            "test-api-key",
            "test-agent-id",
            "test-stripe-key",
        ],
    )
    def test_startup_reads_secret_once_and_stores_it_on_app(self, get_secret):
        with TestClient(app):
            self.assertEqual(app.state.openai_api_key, "test-api-key")
            self.assertEqual(app.state.openai_agent_id, "test-agent-id")
            self.assertEqual(app.state.stripe_api_key, "test-stripe-key")

        self.assertEqual(
            [call.args[0] for call in get_secret.call_args_list],
            [
                "FishinSecret_OpenAI",
                "FishinSecret_Agent_Id",
                "FishinSecret_Stripe_API_Key",
            ],
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
                user=None,
            )

        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("External provider", raised.exception.detail)
        serve_forecast.assert_called_once()

    @patch(
        "routers.forecast_router.forecast_service.serve_forecast",
    )
    @patch("routers.forecast_router.has_active_subscription", return_value=True)
    def test_active_subscriber_receives_ai_evaluation(
        self, has_active_subscription, serve_forecast
    ):
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
            user={"id": "subscriber-1"},
        )

        self.assertIs(response, forecast)
        self.assertEqual(forecast.temp, 80)
        self.assertIsNotNone(response.evaluation_id)
        self.assertEqual(evaluation_jobs[response.evaluation_id]["status"], "pending")
        self.assertEqual(
            evaluation_jobs[response.evaluation_id]["user_id"], "subscriber-1"
        )
        self.assertEqual(len(background_tasks.tasks), 1)
        serve_forecast.assert_called_once()
        has_active_subscription.assert_called_once_with("subscriber-1")

    @patch("routers.forecast_router.has_active_subscription", return_value=False)
    @patch("routers.forecast_router.forecast_service.serve_forecast")
    def test_forecast_data_is_free_without_ai_evaluation(
        self, serve_forecast, has_active_subscription
    ):
        forecast = Mock()
        serve_forecast.return_value = forecast
        background_tasks = BackgroundTasks()

        response = get_forecast(
            request=Mock(app=Mock(state=Mock(evaluation_jobs={}))),
            background_tasks=background_tasks,
            city="Miami",
            state="FL",
            date=date.today().isoformat(),
            user={"id": "free-user"},
        )

        self.assertIs(response, forecast)
        self.assertIsNone(response.evaluation_id)
        self.assertEqual(len(background_tasks.tasks), 0)
        has_active_subscription.assert_called_once_with("free-user")

    @patch("routers.forecast_router.forecast_service.serve_forecast")
    def test_unauthenticated_forecast_data_remains_free(self, serve_forecast):
        forecast = Mock()
        serve_forecast.return_value = forecast

        response = get_forecast(
            request=Mock(app=Mock(state=Mock(evaluation_jobs={}))),
            background_tasks=BackgroundTasks(),
            city="Miami",
            state="FL",
            date=date.today().isoformat(),
            user=None,
        )

        self.assertIs(response, forecast)
        self.assertIsNone(response.evaluation_id)

    def test_evaluation_status_returns_completed_result(self):
        request = Mock(
            app=Mock(
                state=Mock(
                    evaluation_jobs={
                        "job-id": {
                            "status": "completed",
                            "ai_evaluation": "Fish at dawn.",
                            "user_id": "subscriber-1",
                        }
                    }
                )
            )
        )

        with patch(
            "routers.forecast_router.has_active_subscription",
            return_value=True,
        ):
            response = get_evaluation_status(
                "job-id", request, user={"id": "subscriber-1"}
            )

        self.assertEqual(response.status, "completed")
        self.assertEqual(response.ai_evaluation, "Fish at dawn.")

    def test_evaluation_status_returns_not_found_for_unknown_job(self):
        request = Mock(app=Mock(state=Mock(evaluation_jobs={})))

        with self.assertRaises(HTTPException) as raised:
            get_evaluation_status("missing", request, user=None)

        self.assertEqual(raised.exception.status_code, 404)

    @patch("routers.forecast_router.OpenAI")
    @patch("routers.forecast_router.has_active_subscription", return_value=False)
    def test_ai_worker_rechecks_subscription_before_calling_openai(
        self, has_active_subscription, openai
    ):
        job = {"status": "pending", "user_id": "subscriber-1"}
        request = Mock(
            app=Mock(
                state=Mock(
                    evaluation_jobs={"job-id": job},
                    openai_api_key="not-used",
                    openai_agent_id="not-used",
                )
            )
        )

        get_evaluation(request, Mock(), "job-id")

        self.assertEqual(job["status"], "failed")
        self.assertIn("active subscription", job["error"])
        has_active_subscription.assert_called_once_with("subscriber-1")
        openai.assert_not_called()

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
