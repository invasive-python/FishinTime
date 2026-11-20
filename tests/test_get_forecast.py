import asyncio
import tempfile
import unittest
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock, mock_open, patch

import pandas as pd
import requests
import httpx2
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient
from openai import OpenAI
from openai.types.beta.agent_session_turn_created_event import AgentSessionTurnCreatedEvent
from openai.types.beta.agent_session_turn_item_added_event import AgentSessionTurnItemAddedEvent
from openai.types.beta.agent_session_turn_item_done_event import AgentSessionTurnItemDoneEvent
from openai.types.beta.agent_session_turn_output_text_delta_event import AgentSessionTurnOutputTextDeltaEvent
from openai.types.beta.agent_session_turn_output_text_done_event import AgentSessionTurnOutputTextDoneEvent

from api import app
from models.weather_schemas import (
    DailyForecast,
    ForecastPeriod,
    ForecastResponse,
    NearshoreForecast,
    PrecipitationCondition,
    PrecipitationInterval,
)
from routers.forecast_router import (
    _evaluation_waiters,
    _notify_evaluation_waiters,
    get_evaluation,
    get_evaluation_status,
    get_forecast,
    stream_evaluation,
)
from services.weather_service import _map_noaa_period
from services.noaa_station_service import AmbiguousStationError


class EvaluationStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_delivers_updates_and_cleans_up(self):
        job = {"status": "pending", "user_id": "subscriber", "ai_evaluation": None}
        request = Mock(app=Mock(state=Mock(evaluation_jobs={"stream-job": job})))
        response = await stream_evaluation("stream-job", request, user={"id": "subscriber"})
        events = response.body_iterator
        self.assertEqual(json.loads((await anext(events))[6:])["ai_evaluation"], None)

        pending = asyncio.create_task(anext(events))
        await asyncio.sleep(0)
        job["ai_evaluation"] = "Fish"
        _notify_evaluation_waiters("stream-job")
        partial = json.loads((await asyncio.wait_for(pending, 1))[6:])
        self.assertEqual(partial["ai_evaluation"], "Fish")
        self.assertEqual(partial["status"], "pending")

        pending = asyncio.create_task(anext(events))
        await asyncio.sleep(0)
        job.update(status="completed", ai_evaluation="Fish at dawn.")
        _notify_evaluation_waiters("stream-job")
        final = json.loads((await asyncio.wait_for(pending, 1))[6:])
        self.assertEqual(final["ai_evaluation"], "Fish at dawn.")
        self.assertEqual(final["status"], "completed")
        with self.assertRaises(StopAsyncIteration):
            await anext(events)
        self.assertNotIn("stream-job", _evaluation_waiters)

    async def test_stream_rejects_other_users_and_cleans_up_on_disconnect(self):
        job = {"status": "pending", "user_id": "subscriber"}
        request = Mock(app=Mock(state=Mock(evaluation_jobs={"stream-job": job})))
        with self.assertRaises(HTTPException) as raised:
            await stream_evaluation("stream-job", request, user={"id": "other"})
        self.assertEqual(raised.exception.status_code, 404)

        response = await stream_evaluation("stream-job", request, user={"id": "subscriber"})
        await anext(response.body_iterator)
        await response.body_iterator.aclose()
        self.assertNotIn("stream-job", _evaluation_waiters)

    async def test_stream_delivers_failure_with_partial_text(self):
        job = {"status": "pending", "user_id": "subscriber", "ai_evaluation": "Fish"}
        request = Mock(app=Mock(state=Mock(evaluation_jobs={"stream-job": job})))
        response = await stream_evaluation("stream-job", request, user={"id": "subscriber"})
        events = response.body_iterator
        await anext(events)
        job.update(status="failed", error="Stream interrupted.")
        _notify_evaluation_waiters("stream-job")
        failed = json.loads((await asyncio.wait_for(anext(events), 1))[6:])
        self.assertEqual((failed["status"], failed["ai_evaluation"], failed["error"]),
                         ("failed", "Fish", "Stream interrupted."))
        with self.assertRaises(StopAsyncIteration):
            await anext(events)
        self.assertNotIn("stream-job", _evaluation_waiters)


class ForecastRouteTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.reasoning_log = Path(directory.name) / "reasoning.log"
        patcher = patch("routers.forecast_router.REASONING_LOG_PATH", self.reasoning_log)
        patcher.start()
        self.addCleanup(patcher.stop)

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
            navigation_script = client.get("/billing/navigation.js")
            config = client.get("/static/config.js")
            stylesheet = client.get("/static/common.css")
            success = client.get("/billing/success")
            cancel = client.get("/billing/cancel")

        self.assertEqual(root.status_code, 200)
        self.assertIn("Find your fishing window", root.text)
        self.assertIn(
            'href="/billing/account?signin=1" data-direct-signin>Sign in</a>',
            root.text,
        )
        self.assertIn('href="/billing/subscribe">Create account</a>', root.text)
        self.assertNotIn("View subscription options", root.text)
        self.assertIn('data-site-navigation', root.text)
        self.assertIn('data-account-welcome', root.text)
        self.assertIn('/billing/navigation.js', root.text)
        self.assertIn('<script src="/billing/client.js" defer></script>', root.text)
        self.assertIn('src="/static/config.js"', root.text)
        self.assertEqual(page.status_code, 200)
        self.assertIn("Unlock AI fishing recommendations", page.text)
        self.assertIn('data-site-navigation', page.text)
        self.assertIn('data-account-welcome', page.text)
        self.assertIn('data-signed-out-only', page.text)
        self.assertIn('data-plan="monthly">Choose monthly</button>', page.text)
        self.assertIn('data-plan="annual">Choose annual</button>', page.text)
        self.assertEqual(account_page.status_code, 200)
        self.assertIn("Sign in and manage your account", account_page.text)
        self.assertIn('data-site-navigation', account_page.text)
        self.assertIn('data-account-welcome', account_page.text)
        self.assertIn("oauth-navigation-pending body { visibility: hidden; }", account_page.text)
        self.assertIn('classList.add("oauth-navigation-pending")', account_page.text)
        self.assertIn("Change password", account_page.text)
        self.assertEqual(client_script.status_code, 200)
        self.assertIn('sessionStorage.removeItem("fishintime_last_forecast")', client_script.text)
        self.assertIn('sessionStorage.setItem("fishintime_signed_out", "true")', client_script.text)
        self.assertIn("oauth2/authorize", client_script.text)
        self.assertIn('callback.searchParams.get("signin") === "1"', client_script.text)
        self.assertIn('window.location.replace("/")', client_script.text)
        self.assertIn("localStorage.setItem(tokenStorageKey, result.access_token)", client_script.text)
        self.assertIn("sessionStorage.setItem(stateStorageKey, state)", client_script.text)
        self.assertIn("sessionStorage.setItem(verifierStorageKey, verifier)", client_script.text)
        self.assertIn('error.code = "OAUTH_STATE_INVALID"', client_script.text)
        self.assertIn(
            'sessionStorage.getItem(oauthStateRetryStorageKey) !== "1"',
            client_script.text,
        )
        self.assertIn(
            'searchParams.get("manage") !== "1"', client_script.text
        )
        self.assertEqual(navigation_script.status_code, 200)
        self.assertIn("/api/billing/account", navigation_script.text)
        self.assertIn("Welcome", navigation_script.text)
        self.assertIn('closest("[data-direct-signin]")', navigation_script.text)
        self.assertIn("oauth2/authorize", navigation_script.text)
        self.assertIn('href: "/"', navigation_script.text)
        self.assertIn('href: "/billing/account?manage=1"', navigation_script.text)
        self.assertIn("localStorage.getItem(tokenStorageKey)", navigation_script.text)
        self.assertEqual(config.status_code, 200)
        self.assertEqual(stylesheet.status_code, 200)
        self.assertIn("background-image", stylesheet.text)
        self.assertEqual(success.status_code, 200)
        self.assertEqual(cancel.status_code, 200)
        self.assertIn('data-site-navigation', success.text)
        self.assertIn('data-site-navigation', cancel.text)
        self.assertIn('data-account-welcome', success.text)
        self.assertIn('data-account-welcome', cancel.text)
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
                "FishinSecret_Stripe_API",
            ],
        )

    @patch.dict("os.environ", {"STRIPE_MODE": "sandbox"})
    @patch(
        "api.get_secret",
        side_effect=[
            "test-api-key",
            "test-agent-id",
            "test-sandbox-stripe-key",
        ],
    )
    def test_sandbox_startup_reads_sandbox_stripe_secret(self, get_secret):
        with TestClient(app):
            self.assertEqual(app.state.stripe_mode, "sandbox")
            self.assertEqual(app.state.stripe_api_key, "test-sandbox-stripe-key")

        self.assertEqual(
            get_secret.call_args_list[-1].args[0],
            "FishinSecret_Stripe_API_Key",
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
        side_effect=AmbiguousStationError("Multiple stations; specify station_id."),
    )
    def test_ambiguous_station_name_is_reported_as_conflict(self, serve_forecast):
        with self.assertRaises(HTTPException) as raised:
            get_forecast(
                request=Mock(),
                background_tasks=BackgroundTasks(),
                city="Same Name",
                state="FL",
                date=date.today().isoformat(),
                user=None,
            )
        self.assertEqual(raised.exception.status_code, 409)

    @patch("builtins.open", new=mock_open())
    @patch("routers.forecast_router.forecast_service.serve_forecast")
    def test_station_id_is_passed_to_forecast(self, serve_forecast):
        serve_forecast.return_value = Mock()
        serve_forecast.return_value.model_dump_json.return_value = "{}"
        get_forecast(
            request=Mock(app=Mock(state=Mock(evaluation_jobs={}))),
            background_tasks=BackgroundTasks(),
            city="Same Name",
            state="FL",
            date=date.today().isoformat(),
            user=None,
            station_id="8724224",
        )
        serve_forecast.assert_called_once_with(
            "Same Name", "FL", date.today().isoformat(), "8724224"
        )

    @patch("builtins.open", new=mock_open())
    @patch("routers.forecast_router.forecast_service.serve_forecast")
    def test_passes_centered_window_to_forecast(self, serve_forecast):
        from datetime import timedelta
        selected = date.today() + timedelta(days=4)
        start = selected - timedelta(days=3)
        forecast = Mock()
        forecast.model_dump_json.return_value = "{}"
        serve_forecast.return_value = forecast
        get_forecast(
            request=Mock(), background_tasks=BackgroundTasks(), city="Miami", state="FL",
            date=selected.isoformat(), user=None, station_id="8723214",
            start_date=start.isoformat(),
        )
        serve_forecast.assert_called_once_with(
            "Miami", "FL", selected.isoformat(), "8723214", start_date=start
        )

    def test_rejects_window_that_excludes_selected_date(self):
        with self.assertRaises(HTTPException) as raised:
            get_forecast(
                request=Mock(), background_tasks=BackgroundTasks(), city="Miami", state="FL",
                date=date.today().isoformat(), user=None, start_date="2000-01-01",
            )
        self.assertEqual(raised.exception.status_code, 400)

    @patch("builtins.open", new=mock_open())
    @patch("routers.forecast_router.forecast_service.serve_forecast")
    def test_signed_in_user_receives_ai_evaluation(self, serve_forecast):
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

    @patch("builtins.open", new=mock_open())
    @patch("routers.forecast_router.forecast_service.serve_forecast")
    def test_signed_in_user_without_subscription_receives_ai_evaluation(
        self, serve_forecast
    ):
        forecast = Mock()
        forecast.model_dump_json.return_value = "{}"
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
        self.assertIsNotNone(response.evaluation_id)
        self.assertEqual(len(background_tasks.tasks), 1)

    @patch("builtins.open", new=mock_open())
    @patch("routers.forecast_router.forecast_service.serve_forecast")
    def test_unauthenticated_forecast_data_remains_free(self, serve_forecast):
        forecast = Mock()
        forecast.model_dump_json.return_value = "{}"
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

    @patch("builtins.open", new_callable=mock_open)
    @patch("routers.forecast_router.forecast_service.serve_forecast")
    def test_writes_serialized_forecast_including_wave_dataframe(
        self, serve_forecast, file_open
    ):
        forecast = ForecastResponse(
            city="Miami", city_lat="25.76", city_long="-80.19",
            date=date.today().isoformat(), precipitation_probability=20,
            start_time="2026-11-19 06:00", temp=80,
            wind_speed_max=10, wind_speed_min=5, wind_direction="E",
            moon_current_phase="Full Moon", moon_closest_phase="Full Moon",
            moon_closest_phase_date="2026-11-19", moon_brightness="100%",
            predictions=[], detailed_forecast="Clear",
            waves=pd.DataFrame([{"wave_height": 1.2}]),
        )
        serve_forecast.return_value = forecast

        get_forecast(
            request=Mock(), background_tasks=BackgroundTasks(), city="Miami",
            state="FL", date=date.today().isoformat(), user=None,
        )

        file_open.assert_called_once_with("forecast.json", "w", encoding="utf-8")
        output = json.loads(file_open().write.call_args.args[0])
        self.assertEqual(output["city"], "Miami")
        self.assertEqual(output["waves"], [{"wave_height": 1.2}])

    @patch("builtins.open", new_callable=mock_open)
    @patch("routers.forecast_router.forecast_service.serve_forecast", return_value=None)
    def test_missing_forecast_does_not_overwrite_file(self, serve_forecast, file_open):
        with self.assertRaises(HTTPException) as raised:
            get_forecast(
                request=Mock(), background_tasks=BackgroundTasks(), city="Miami",
                state="FL", date=date.today().isoformat(), user=None,
            )
        self.assertEqual(raised.exception.status_code, 404)
        file_open.assert_not_called()

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
    def test_ai_stream_publishes_only_root_final_text_and_reconciles_parts(self, openai):
        job = {"status": "pending", "user_id": "subscriber-1"}
        request = Mock(app=Mock(state=Mock(
            evaluation_jobs={"job-id": job},
            openai_api_key="test-key", openai_agent_id="test-agent",
        )))
        base = {"event_id": "event", "session_id": "session", "turn_id": "root"}
        root = AgentSessionTurnCreatedEvent.model_validate({
            **base, "type": "agent.session.turn.created",
            "turn": {"id": "root", "agent_id": "agent", "created_at": 1,
                     "object": "agent.session.turn", "session_id": "session",
                     "status": "in_progress", "subagent_id": None},
        })

        def added(item_id, phase):
            return AgentSessionTurnItemAddedEvent.model_validate({
                **base, "turn_id": None, "type": "agent.session.turn.item.added", "output_index": 0,
                "item": {"id": item_id, "type": "message", "role": "assistant",
                         "phase": phase, "status": "in_progress", "turn_id": "root",
                         "content": []},
            })

        def delta(item_id, text, *, turn: str | None = "root", output=0, content=0):
            return AgentSessionTurnOutputTextDeltaEvent.model_validate({
                **base, "turn_id": turn, "type": "agent.session.turn.output_text.delta",
                "item_id": item_id, "output_index": output, "content_index": content,
                "delta": text,
            })

        corrected = AgentSessionTurnOutputTextDoneEvent.model_validate({
            **base, "type": "agent.session.turn.output_text.done", "item_id": "answer",
            "output_index": 0, "content_index": 0, "text": "Fish at dawn.",
        })
        done_without_deltas = AgentSessionTurnItemDoneEvent.model_validate({
            **base, "type": "agent.session.turn.item.done", "output_index": 1,
            "item": {"id": "second", "type": "message", "role": "assistant",
                     "phase": "final_answer", "status": "completed", "turn_id": "root",
                     "content": [{"type": "output_text", "text": " Bring bait."}]},
        })
        events = [
            root, added("commentary", "commentary"), delta("commentary", "internal"),
            added("answer", "final_answer"), delta("answer", "Fish", turn=None),
            delta("answer", "subagent", turn="child"), delta("answer", " at"),
            corrected, done_without_deltas,
        ]
        snapshots = []

        def events_with_snapshots():
            for event in events:
                yield event
                snapshots.append(get_evaluation_status(
                    "job-id", request, user={"id": "subscriber-1"}
                ).ai_evaluation)

        stream = MagicMock()
        stream.__enter__.return_value = stream
        stream.__iter__.side_effect = events_with_snapshots
        stream.get_final_result.return_value = Mock(output_text="Fish at dawn. Bring bait.")
        openai.return_value.beta.agents.sessions.create.return_value.with_result_collection.return_value = stream
        forecast = Mock()
        forecast.model_dump_json.return_value = "{}"

        get_evaluation(request, forecast, "job-id")

        self.assertEqual(snapshots, [
            None, None, None, None, "Fish", "Fish", "Fish at",
            "Fish at dawn.", "Fish at dawn. Bring bait.",
        ])
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["ai_evaluation"], "Fish at dawn. Bring bait.")
        stream.get_final_result.assert_called_once_with()

        def interrupted_events():
            yield root
            yield added("answer", "final_answer")
            yield delta("answer", "Fish")
            raise RuntimeError("stream interrupted")

        job.update(status="pending")
        job.pop("ai_evaluation")
        stream.__iter__.side_effect = interrupted_events
        with self.assertLogs("routers.forecast_router", level="ERROR"):
            get_evaluation(request, forecast, "job-id")
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["ai_evaluation"], "Fish")
        self.assertIn("stream interrupted", job["error"])
        with self.assertRaises(HTTPException) as raised:
            get_evaluation_status("job-id", request, user={"id": "different-user"})
        self.assertEqual(raised.exception.status_code, 404)

    def test_ai_stream_collects_final_result_from_sdk_events(self):
        job = {"status": "pending", "user_id": "subscriber-1"}
        request = Mock(app=Mock(state=Mock(
            evaluation_jobs={"job-id": job},
            openai_api_key="test-key", openai_agent_id="test-agent",
        )))
        turn = {
            "id": "root", "agent_id": "agent", "created_at": 1,
            "object": "agent.session.turn", "session_id": "session",
            "status": "in_progress", "subagent_id": None,
        }
        message = {
            "id": "answer", "type": "message", "role": "assistant",
            "phase": "final_answer", "status": "in_progress", "turn_id": "root",
            "content": [],
        }
        events = [
            {"type": "agent.session.turn.created", "turn": turn},
            {"type": "agent.session.turn.reasoning_summary_text.delta", "item_id": "reasoning",
             "output_index": 0, "summary_index": 0, "delta": "Checking tides"},
            {"type": "agent.session.turn.reasoning_summary_text.done", "item_id": "reasoning",
             "output_index": 0, "summary_index": 0, "text": "Checking tides and wind"},
            {"type": "agent.session.turn.item.added", "output_index": 1,
             "item": {**message, "id": "note", "phase": "commentary"}},
            {"type": "agent.session.turn.output_text.delta", "item_id": "note",
             "output_index": 1, "content_index": 0, "delta": "Reviewing wind"},
            {"type": "agent.session.turn.output_text.done", "item_id": "note",
             "output_index": 1, "content_index": 0, "text": "Reviewing wind"},
            {"type": "agent.session.turn.item.added", "item": message, "output_index": 2},
            {"type": "agent.session.turn.output_text.delta", "item_id": "answer",
             "output_index": 2, "content_index": 0, "delta": "Fish"},
            {"type": "agent.session.turn.item.done", "output_index": 2,
             "item": {**message, "status": "completed",
                      "content": [{"type": "output_text", "text": "Fish at dawn."}]}},
            {"type": "agent.session.turn.completed", "turn": {**turn, "status": "completed"}},
            {"type": "agent.session.idle", "session": {"id": "session"}},
        ]
        snapshots = []

        class EventBytes(httpx2.SyncByteStream):
            def __iter__(self):
                for index, event in enumerate(events):
                    payload = {"event_id": str(index), "session_id": "session",
                               "turn_id": "root", **event}
                    yield f"data: {json.dumps(payload)}\n\n".encode()
                    snapshots.append((event["type"], job.get("ai_evaluation"), job.get("ai_activity")))

        def respond(http_request):
            return httpx2.Response(
                200, headers={"content-type": "text/event-stream"}, stream=EventBytes()
            )

        client = OpenAI(api_key="test-key", http_client=httpx2.Client(
            transport=httpx2.MockTransport(respond)
        ))
        forecast = Mock()
        forecast.model_dump_json.return_value = "{}"
        with patch("routers.forecast_router.OpenAI", return_value=client):
            get_evaluation(request, forecast, "job-id")

        reasoning = "agent.session.turn.reasoning_summary_text.delta"
        text = "agent.session.turn.output_text.delta"
        self.assertIn((reasoning, None, "Checking tides"), snapshots)
        self.assertIn((text, None, "Reviewing wind"), snapshots)
        self.assertIn((text, "Fish", None), snapshots)
        self.assertIsNone(job["ai_activity"])
        logged = self.reasoning_log.read_text(encoding="utf-8")
        self.assertIn("reasoning step\nChecking tides and wind\n", logged)
        self.assertIn("commentary\nReviewing wind\n", logged)
        self.assertIn("item added: message:final_answer", logged)
        self.assertNotIn("Fish at dawn", logged)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["ai_evaluation"], "Fish at dawn.")
        client.close()

    @patch("routers.forecast_router.OpenAI")
    def test_ai_worker_runs_for_signed_in_user_without_subscription(self, openai):
        job = {"status": "pending", "user_id": "subscriber-1"}
        request = Mock(
            app=Mock(
                state=Mock(
                    evaluation_jobs={"job-id": job},
                    openai_api_key="sk-test-openai-key",
                    openai_agent_id="agent-test-id",
                )
            )
        )
        stream = MagicMock()
        stream.__enter__ = Mock(return_value=stream)
        stream.__exit__ = Mock(return_value=None)
        stream.get_final_result.return_value = Mock(output_text="Fish at dawn.")
        openai.return_value.beta.agents.sessions.create.return_value.with_result_collection.return_value = stream
        forecast = Mock()
        forecast.model_dump_json.return_value = (
            '{"weather_forecast":[{"name":"Tuesday"}],'
            '"predictions":[{"t":"2026-11-20 06:00"}],'
            '"daily_forecasts":[{"date":"2026-11-20","moon_brightness":"80%",'
            '"pressure":{"error":"No forecast"}}],'
            '"nearshore":{"wave_height":{"values":[{"value":2}]}}}'
        )

        get_evaluation(request, forecast, "job-id")

        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["ai_evaluation"], "Fish at dawn.")
        openai.assert_called_once_with(api_key="sk-test-openai-key")
        prompt = openai.return_value.beta.agents.sessions.create.call_args.kwargs["input"]
        self.assertIn('"weather_forecast":[{"name":"Tuesday"}]', prompt)
        self.assertIn('"predictions":[{"t":"2026-11-20 06:00"}]', prompt)
        self.assertIn('"moon_brightness":"80%"', prompt)
        self.assertIn('"pressure":{"error":"No forecast"}', prompt)
        self.assertIn('"wave_height":{"values":[{"value":2}]}', prompt)

    def _ai_prompt(self, openai, forecast):
        job = {"status": "pending", "user_id": "subscriber-1"}
        request = Mock(app=Mock(state=Mock(
            evaluation_jobs={"job-id": job},
            openai_api_key="test-key", openai_agent_id="test-agent",
        )))
        stream = MagicMock()
        stream.__enter__ = Mock(return_value=stream)
        stream.__exit__ = Mock(return_value=None)
        stream.get_final_result.return_value = Mock(output_text="Fish at dawn.")
        openai.return_value.beta.agents.sessions.create.return_value.with_result_collection.return_value = stream
        get_evaluation(request, forecast, "job-id")
        return openai.return_value.beta.agents.sessions.create.call_args.kwargs["input"]

    @patch("routers.forecast_router.OpenAI")
    def test_ai_prompt_states_date_and_station_timezone_and_forbids_lookups(self, openai):
        forecast = Mock(date="2026-11-21", timezone="America/Los_Angeles", city="Seaside")
        forecast.station = Mock(state="OR")
        forecast.model_dump_json.return_value = "{}"

        prompt = self._ai_prompt(openai, forecast)

        self.assertIn("Fishing location: Seaside, OR.", prompt)
        self.assertIn("Selected date: Saturday, November 21, 2026 (2026-11-21).", prompt)
        self.assertIn("Station time zone: America/Los_Angeles", prompt)
        self.assertIn("Today's date at the station:", prompt)
        self.assertNotIn("America/New_York", prompt)
        self.assertIn("Do not use web search, browsing, or any other tool", prompt)
        self.assertIn("NWS weather forecast", prompt)
        self.assertIn("NWS active alerts (alerts)", prompt)
        self.assertIn('Do not rate boat fishing "Insufficient Data" solely', prompt)

    @patch("routers.forecast_router.OpenAI")
    def test_ai_prompt_does_not_invent_a_timezone_when_none_is_supplied(self, openai):
        forecast = Mock()
        forecast.model_dump_json.return_value = "{}"

        prompt = self._ai_prompt(openai, forecast)

        self.assertIn("Station time zone: not supplied", prompt)
        self.assertNotIn("America/", prompt)

    @patch("routers.forecast_router.OpenAI")
    def test_ai_worker_uses_secret_values_loaded_at_startup(self, openai):
        job = {"status": "pending", "user_id": "subscriber-1"}
        request = Mock(
            app=Mock(
                state=Mock(
                    evaluation_jobs={"job-id": job},
                    openai_api_key="sk-test-openai-key",
                    openai_agent_id="agent-test-id",
                )
            )
        )
        stream = MagicMock()
        stream.__enter__ = Mock(return_value=stream)
        stream.__exit__ = Mock(return_value=None)
        stream.get_final_result.return_value = Mock(output_text="Fish at dawn.")
        openai.return_value.beta.agents.sessions.create.return_value.with_result_collection.return_value = stream
        forecast = Mock()
        forecast.model_dump_json.return_value = "{}"

        get_evaluation(request, forecast, "job-id")

        self.assertEqual(openai.call_args.kwargs["api_key"], "sk-test-openai-key")
        self.assertEqual(
            openai.return_value.beta.agents.sessions.create.call_args.kwargs[
                "agent_id"
            ],
            "agent-test-id",
        )
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["ai_evaluation"], "Fish at dawn.")

    @patch("routers.forecast_router.OpenAI")
    def test_ai_omits_only_derived_waves_when_nearshore_is_available(self, openai):
        start = date(2026, 11, 20)
        series_names = [
            "wave_height", "wave_period", "wave_direction",
            "primary_swell_height", "primary_swell_period", "primary_swell_direction",
            "secondary_swell_height", "secondary_swell_period", "secondary_swell_direction",
            "wind_wave_height", "wind_wave_period", "wind_wave_direction",
            "wind_speed", "wind_direction",
        ]
        nearshore = NearshoreForecast.model_validate({
            "source": "NWS", "timezone": "America/New_York", "forecast_days": 7,
            "grid": {"office": "MFL", "x": 1, "y": 2, "lat": 25.76,
                     "lng": -80.19, "distance_km": 1, "inferred": False},
            **{name: {"unit": "ft", "values": []} for name in series_names},
            "wave_height": {"unit": "ft", "values": [{
                "valid_start": "2026-11-20T05:00:00Z", "duration": "P7D", "value": 2,
            }]},
        })
        forecast = ForecastResponse(
            city="Miami", city_lat="25.76", city_long="-80.19",
            date=start.isoformat(), precipitation_probability=20, start_time=None,
            temp=80, wind_speed_max=10, wind_speed_min=5, wind_direction="E",
            moon_current_phase="Full Moon", moon_closest_phase="Full Moon",
            moon_closest_phase_date="2026-11-20", moon_brightness="100%",
            predictions=[{"t": "2026-11-20 06:00", "v": "2", "type": "H"}],
            daily_forecasts=[DailyForecast(date=start + timedelta(days=day)) for day in range(7)],
            weather_forecast=[
                ForecastPeriod(
                    name=f"Day {day + 1}",
                    start_time=datetime(2026, 11, 20, tzinfo=UTC) + timedelta(days=day),
                    end_time=datetime(2026, 11, 21, tzinfo=UTC) + timedelta(days=day),
                )
                for day in range(7)
            ],
            precipitation_forecast=[PrecipitationInterval(
                start_time=datetime(2026, 11, 20, tzinfo=UTC),
                end_time=datetime(2026, 11, 21, tzinfo=UTC),
                conditions=[PrecipitationCondition(weather="rain", coverage="chance")],
            )],
            nearshore=nearshore, detailed_forecast="Clear",
            waves=pd.DataFrame([
                {"date": f"{start + timedelta(days=hour // 24)}T{hour % 24:02d}:00",
                 "wave_height": 2.0}
                for hour in range(168)
            ]),
        )
        stream = MagicMock()
        stream.__enter__ = Mock(return_value=stream)
        stream.__exit__ = Mock(return_value=None)
        stream.get_final_result.return_value = Mock(output_text="Fish at dawn.")
        openai.return_value.beta.agents.sessions.create.return_value.with_result_collection.return_value = stream

        for with_nearshore in (True, False):
            with self.subTest(with_nearshore=with_nearshore):
                if not with_nearshore:
                    forecast.nearshore = None
                expected = json.loads(forecast.model_dump_json())
                job = {"status": "pending", "user_id": "subscriber-1"}
                request = Mock(app=Mock(state=Mock(
                    evaluation_jobs={"job-id": job},
                    openai_api_key="test-key", openai_agent_id="test-agent",
                )))
                get_evaluation(request, forecast, "job-id")
                prompt = openai.return_value.beta.agents.sessions.create.call_args.kwargs["input"]
                data = prompt.split("FORECAST DATA:", 1)[1].split("PRIMARY OBJECTIVE:", 1)[0]
                actual = json.loads(data.strip())
                if with_nearshore:
                    expected.pop("waves")
                    self.assertNotIn("waves", actual)
                    self.assertEqual(len(actual["daily_forecasts"]), 7)
                    self.assertEqual(len(actual["weather_forecast"]), 7)
                    self.assertEqual(actual["precipitation_forecast"][0]["conditions"][0]["weather"], "rain")
                    self.assertEqual(len(actual["nearshore"]["wave_height"]["values"]), 1)
                    self.assertLess(len(data.strip()), len(forecast.model_dump_json()) * 0.6)
                else:
                    self.assertEqual(len(actual["waves"]), 168)
                self.assertEqual(actual, expected)
                self.assertEqual(job["status"], "completed")
                self.assertEqual(forecast.waves.iloc[0]["wave_height"], 2.0)

    def test_openapi_registers_current_forecast_contract(self):
        schema = app.openapi()
        operation = schema["paths"]["/forecast/get_forecast"]["get"]
        parameters = {
            parameter["name"]: parameter for parameter in operation["parameters"]
        }

        self.assertEqual(set(parameters), {"city", "state", "date", "station_id", "start_date"})
        self.assertTrue(all(parameters[name]["required"] for name in ("city", "state", "date")))
        self.assertFalse(parameters["station_id"]["required"])
        response_reference = operation["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        self.assertEqual(response_reference, "#/components/schemas/ForecastResponse")


if __name__ == "__main__":
    unittest.main()
