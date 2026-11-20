import asyncio
import logging
import tempfile
import threading
import time
import uuid
from datetime import date as date_type
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Annotated, Any

import requests
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
)
from fastapi.responses import StreamingResponse
from openai import OpenAI

from billing.auth import get_optional_authenticated_user
from models.weather_schemas import EvaluationJobResponse, ForecastResponse
from services import forecast_service
from services.noaa_station_service import AmbiguousStationError

router = APIRouter()
logger = logging.getLogger(__name__)
REASONING_LOG_PATH = Path(tempfile.gettempdir()) / "fishintime_ai_reasoning.log"
_reasoning_log_lock = threading.Lock()
_evaluation_waiters_lock = threading.Lock()
_evaluation_waiters: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Event]]] = {}


def _record_reasoning_step(evaluation_id: str, elapsed: float, kind: str, text: str = "") -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {evaluation_id[:8]} +{elapsed:.1f}s {kind}"
    if text:
        line += "\n" + text.rstrip() + "\n"
    try:
        with _reasoning_log_lock:
            REASONING_LOG_PATH.touch(mode=0o600, exist_ok=True)
            with REASONING_LOG_PATH.open("a", encoding="utf-8") as log:
                log.write(line + "\n")
    except OSError:
        logger.warning("Could not write the AI reasoning log.", exc_info=True)


def _notify_evaluation_waiters(evaluation_id: str) -> None:
    with _evaluation_waiters_lock:
        for loop, event in _evaluation_waiters.get(evaluation_id, ()):
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:
                logger.warning("AI evaluation stream event loop is closed.")


def is_today_or_future(date_string: str, date_format: str = "%Y-%m-%d") -> bool:
    try:
        input_date = datetime.strptime(date_string, date_format).date()
        today = date_type.today()

        return input_date >= today

    except ValueError:
        return False


@router.get(
    "/forecast/get_forecast",
    summary="Get forecast periods for a city and date",
    tags=["get_forecast"],
    responses={
        400: {"description": "Date must be today or in the future."},
        404: {"description": "Forecast or NOAA tide station not found."},
        409: {"description": "Station name is ambiguous; specify station_id."},
        502: {"description": "External provider request or response failed"}
    },
)
def get_forecast(
    request: Request,
    background_tasks: BackgroundTasks,
    city: str,
    state: str,
    date: str,
    user: Annotated[
        dict[str, Any] | None, Depends(get_optional_authenticated_user)
    ],
    station_id: str | None = None,
    start_date: str | None = None,
) -> ForecastResponse:
    try:
        if not is_today_or_future(date):
            raise HTTPException(status_code=400, detail="Date must be today or in the future.")

        if start_date is not None:
            try:
                first_day = date_type.fromisoformat(start_date)
                selected_day = date_type.fromisoformat(date)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid forecast start date.") from exc
            if not first_day <= selected_day < first_day + timedelta(days=7):
                raise HTTPException(
                    status_code=400,
                    detail="Selected date must be within the seven-day forecast window.",
                )
            forecast = forecast_service.serve_forecast(
                city, state, date, station_id, start_date=first_day
            )
        else:
            forecast = forecast_service.serve_forecast(city, state, date, station_id)

        if forecast is None:
            raise HTTPException(
                status_code=404,
                detail=f"No forecast or NOAA tide station found for {city} on {date}.",
            )

        with open("forecast.json", "w", encoding="utf-8") as f:
            f.write(forecast.model_dump_json(indent=2))

        if user is not None:
            evaluation_id = str(uuid.uuid4())
            evaluation_jobs = getattr(request.app.state, "evaluation_jobs", None)
            if evaluation_jobs is None:
                evaluation_jobs = {}
                request.app.state.evaluation_jobs = evaluation_jobs
            evaluation_jobs[evaluation_id] = {
                "status": "pending",
                "user_id": str(user["id"]),
            }
            background_tasks.add_task(
                get_evaluation, request, forecast, evaluation_id
            )
            forecast.evaluation_id = evaluation_id
        else:
            forecast.evaluation_id = None

        return forecast

    except HTTPException:
        raise
    except AmbiguousStationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"External provider request or response failed: {exc}",
        ) from exc 

@router.get(
    "/forecast/evaluation/{evaluation_id}",
    summary="Get the status and result of an AI fishing evaluation",
    tags=["get_forecast"],
    responses={404: {"description": "AI evaluation not found."},401: {"description": "Sign-in required."}}
)
def get_evaluation_status(
    evaluation_id: str,
    request: Request,
    user: Annotated[
        dict[str, Any] | None, Depends(get_optional_authenticated_user)
    ],
) -> EvaluationJobResponse:
    evaluation_jobs = getattr(request.app.state, "evaluation_jobs", {})
    job = evaluation_jobs.get(evaluation_id)
    if job is None:
        raise HTTPException(status_code=404, detail="AI evaluation not found.")
    if user is None:
        raise HTTPException(status_code=401, detail="Sign-in required.")
    if job.get("user_id") != str(user["id"]):
        raise HTTPException(status_code=404, detail="AI evaluation not found.")
    return EvaluationJobResponse(
        status=job["status"],
        ai_evaluation=job.get("ai_evaluation"),
        activity=job.get("ai_activity"),
        error=job.get("error"),
    )


@router.get(
    "/forecast/evaluation/{evaluation_id}/stream",
    summary="Stream an AI fishing evaluation",
    responses={404: {"description": "AI evaluation not found."}, 401: {"description": "Sign-in required."}},
)
async def stream_evaluation(
    evaluation_id: str,
    request: Request,
    user: Annotated[
        dict[str, Any] | None, Depends(get_optional_authenticated_user)
    ],
) -> StreamingResponse:
    get_evaluation_status(evaluation_id, request, user)

    async def events():
        loop = asyncio.get_running_loop()
        changed = asyncio.Event()
        waiter = (loop, changed)
        with _evaluation_waiters_lock:
            _evaluation_waiters.setdefault(evaluation_id, []).append(waiter)
        previous = None
        try:
            while True:
                changed.clear()
                result = get_evaluation_status(evaluation_id, request, user)
                payload = result.model_dump_json()
                if payload != previous:
                    previous = payload
                    yield f"data: {payload}\n\n"
                if result.status in ("completed", "failed"):
                    return
                try:
                    await asyncio.wait_for(changed.wait(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            with _evaluation_waiters_lock:
                waiters = _evaluation_waiters[evaluation_id]
                waiters.remove(waiter)
                if not waiters:
                    del _evaluation_waiters[evaluation_id]

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


def _evaluation_context(forecast: ForecastResponse) -> str:
    try:
        zone = ZoneInfo(forecast.timezone)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        zone = None
    try:
        selected = date_type.fromisoformat(forecast.date)
    except (TypeError, ValueError):
        selected = None
    today = datetime.now(zone).date() if zone else date_type.today()
    station = getattr(forecast, "station", None)
    place = ", ".join(
        part for part in (forecast.city, getattr(station, "state", None))
        if isinstance(part, str) and part
    )
    lines = []
    if place:
        lines.append(f"- Fishing location: {place}.")
    if selected is not None:
        lines.append(f"- Selected date: {_long_date(selected)} ({selected.isoformat()}).")
    lines.append(f"- Today's date at the station: {_long_date(today)}.")
    lines.append(
        f"- Station time zone: {zone.key}, determined by the National Weather "
        "Service from the station's coordinates. Use this time zone for all times."
        if zone else
        "- Station time zone: not supplied. Use the UTC offsets in the supplied times."
    )
    return "\n        ".join(lines)


def _long_date(value: date_type) -> str:
    return f"{value:%A, %B} {value.day}, {value.year}"


def get_evaluation(
    request: Request, forecast: ForecastResponse, evaluation_id: str
) -> None:
    job = request.app.state.evaluation_jobs[evaluation_id]
    try:
        api_key = request.app.state.openai_api_key
        agent_key = request.app.state.openai_agent_id
        ai_forecast = forecast.model_dump_json(
            exclude={"waves"} if forecast.nearshore is not None else set()
        )
        evaluation_context = _evaluation_context(forecast)

        prompt = f"""
        You are a marine weather analyst and recreational fishing advisor
        with expertise in coastal meteorology, ocean conditions, tides,
        and regional fishing practices.

        Your task is to evaluate the supplied marine and weather forecast
        data and provide practical fishing recommendations for the user's
        selected location and date.

        LOCATION AND DATE:
        {evaluation_context}

        INFORMATION SOURCES:
        Everything needed for this evaluation is supplied in the forecast
        data below and in the notes in this prompt. The supplied data
        contains: the NWS weather forecast (weather_forecast,
        precipitation_forecast), the NWS marine grid forecast (nearshore),
        NOAA tide predictions (predictions, H = high, L = low), a NOAA
        pressure observation (pressure), a water temperature observation
        (water_temperature), USNO sun and moon data
        (sunrise, sunset, moonrise, moonset, moon phase in daily_forecasts),
        and NWS active alerts (alerts).

        Do not use web search, browsing, or any other tool to look up or
        verify information. This includes NWS or marine forecasts,
        advisories, tides, pressure, sunrise and sunset, surf or rip-current
        reports, fishing reports, and species information. Searching only
        adds delay. If information you would like is not supplied, state
        that limitation instead of looking it up.

        TIME AND UNIT FORMATS:
        - Local station time (no zone suffix): tide prediction "t" values,
        and the start_time, sunrise, sunset, moonrise, moonset, and alert
        times in daily_forecasts and alerts.
        - UTC (trailing "Z"): nearshore valid_start values, which are
        followed by an ISO-8601 duration, and precipitation_forecast
        start_time and end_time. Convert these to the station time zone.
        - weather_forecast start_time and end_time include the local UTC
        offset.
        - pressure and water_temperature observed_at include the station's
        local UTC offset. Water temperature is in degrees Fahrenheit and is
        a recent observation, not a forecast for the selected date.
        - These observations can come from different nearby NOAA stations;
        their station fields identify the source and distance from the
        selected location. Proximity does not guarantee matching conditions.
        - weather_forecast uses degrees Celsius and km/h. daily_forecasts
        use degrees Fahrenheit and mph. Nearshore waves are in feet and
        nearshore wind is in mph.
        - when reporting or generating a response output data in Farenheit,
        feet, mph, etc.

        FORECAST DATA:
        {ai_forecast}

        PRIMARY OBJECTIVE:
        Evaluate whether conditions are favorable for recreational fishing
        from shore and by boat. Identify the best fishing time windows,
        explain the factors influencing those recommendations, and suggest
        appropriate fishing strategies.

        EVALUATION REQUIREMENTS:

        1. DATE AND FORECAST PERIOD
        - The user's selected date is the primary date for the evaluation.
        - Evaluate the selected date in detail.
        - Use the surrounding forecast periods to provide a multi-day
        outlook, but do not allow other dates to overshadow the selected date.
        - Use the local time zone associated with the selected fishing location.
        - Clearly distinguish forecast conditions from observed conditions.

        2. SHORE FISHING
        Evaluate conditions specifically relevant to fishing from beaches,
        piers, jetties, and other accessible shore locations.

        Consider:
        - Nearshore wave height, period, and direction.
        - Swell height, period, and direction.
        - Wind speed and direction.
        - Weather conditions and precipitation.
        - Tide predictions and tidal movement.
        - Potentially hazardous surf or coastal conditions.

        Prioritize nearshore conditions over offshore conditions when
        evaluating shore fishing.

        3. BOAT FISHING
        Evaluate conditions relevant to recreational boating and fishing
        offshore or in coastal waters.

        Consider:
        - Wave height, period, and direction for the nearshore and
        coastal waters covered by the supplied data.
        - Swell conditions.
        - Wind speed and direction.
        - Weather conditions and precipitation.
        - Tide predictions and currents, when available.
        - Potentially hazardous marine conditions.

        Do not assume that favorable shore fishing conditions imply
        favorable boating conditions.

        The supplied marine data covers nearshore and coastal waters only;
        offshore conditions are not supplied. Rate boating for the waters
        the data covers and state that offshore conditions were not
        evaluated. Do not rate boat fishing "Insufficient Data" solely
        because offshore data is absent.

        4. BEST FISHING TIMES
        Identify the most favorable fishing windows for the selected date.

        Use the interval arrays in the nearshore wave, swell, and wind
        series, weather_forecast periods, precipitation_forecast intervals,
        and tide predictions. A daily start_time is the first interval with a
        chance of precipitation, not a guaranteed or exact precipitation onset.
        00:00 may mean the interval began on a previous day.

        Use sunrise and sunset from daily_forecasts to place windows
        relative to daylight, and the moon phase and moonrise and moonset
        where relevant.

        Consider the relationship between:
        - Incoming and outgoing tides.
        - High and low tide timing.
        - Wave height and period.
        - Wind speed and direction.
        - Weather conditions.
        - Available pressure observations.

        Provide specific time ranges supported by the available forecast
        intervals. Explain why each window is favorable or unfavorable.

        Do not invent intermediate forecast values or imply greater
        time precision than the source data supports.

        5. BAROMETRIC PRESSURE
        NOAA CO-OPS pressure is an observation at its stated observation
        time, not a forecast.

        - Do not infer future pressure.
        - Do not extrapolate pressure trends from a single observation.
        - Do not represent an observed pressure value as a forecast.
        - If pressure observations are unavailable or outdated, state that
        pressure information is unavailable or limited.

        6. DATA QUALITY AND AVAILABILITY
        - If nearshore.grid.inferred is true, treat the conditions as
        estimates from a nearby marine grid cell, not measurements at
        the selected station.
        - If nearshore data is unavailable, explicitly say so.
        Do not substitute offshore conditions and present them as
        nearshore conditions.
        - Do not invent missing measurements, observations, or forecasts.
        - If a data source is stale, incomplete, or unavailable, explain
        how that limits the evaluation.
        - Do not claim that a condition is favorable when the required
        supporting data is unavailable.

        7. FISH SPECIES AND FISHING STRATEGIES
        When sufficient geographic and seasonal context is available:
        - Identify species commonly associated with the selected area
        during this time of year.
        - Treat species guidance as general seasonal knowledge. Recent
        catch reports are not supplied, so do not claim that a species is
        currently being caught.
        - Suggest appropriate bait, lures, and fishing tactics for
        the recommended species.
        - Distinguish shore and boat fishing techniques where relevant.
        - Avoid recommending species or techniques without reasonable
        geographic and seasonal justification.

        8. SAFETY
        Safety takes priority over fishing opportunity.

        - Identify potentially hazardous wind, wave, surf, or weather
        conditions.
        - Do not recommend boat fishing when the available conditions
        suggest unsafe boating conditions.
        - Do not recommend shore fishing when surf or coastal conditions
        present significant hazards.
        - Do not treat this evaluation as a substitute for official
        marine warnings, advisories, or local safety guidance.
        - Use the supplied alerts. If an alert applies to the selected
        date, name it with its local times and let it limit your ratings.
        The alert list covers only the areas described in its coverage
        note. If no alerts are listed, say that no alerts were supplied
        for those areas rather than stating that none exist, and advise
        the user to check the official NWS marine forecast before going.
        - If safety cannot be adequately evaluated due to missing data,
        explicitly state that limitation.

        9. EVALUATION AND CONFIDENCE
        Provide separate qualitative assessments for shore and boat fishing.

        Use these ratings:
        - Excellent
        - Good
        - Fair
        - Poor
        - Not Recommended
        - Insufficient Data

        Base each rating on the available evidence, not an assumed
        relationship between weather and fish activity.

        Explain the primary factors behind each rating.
        Distinguish confidence in the environmental forecast from
        confidence in the fishing recommendation.

        RESPONSE FORMAT:

        Organize the response into these sections:

        Overall Fishing Outlook
        - Brief summary of the conditions on the selected date.
        - Overall assessment and most important considerations for surf/shore fishing.
        - Overall assessment and most important considerations for boat fishing.

        Shore Fishing Evaluation
        - Rating.
        - Conditions and supporting evidence.
        - Best fishing time windows.
        - Recommended species, bait, and tactics when appropriate.

        Boat Fishing Evaluation
        - Rating.
        - Conditions and supporting evidence.
        - Best fishing time windows.
        - Recommended species, bait, and tactics when appropriate.

        Best Fishing Times
        - Rank the best available time windows for the selected date.
        - Explain the conditions supporting each recommendation.
        - Identify periods to avoid when appropriate.

        Multi-Day Outlook
        - Summarize how conditions change over the surrounding
            forecast period.
        - Identify potentially better or worse fishing days.

        Data Limitations and Safety Considerations
        - Identify missing, inferred, stale, or observed-only data.
        - Mention relevant safety concerns.

        USER-FACING RESPONSE RULES:
        - Do not mention JSON, Python, model fields, variable names,
        APIs, or internal data structures.
        - Refer to the location using only the user-provided station,
        state, and city.
        - Refer to the selected date in the response.
        - Use clear, practical language appropriate for recreational
        anglers.
        - Avoid unsupported claims, false precision, and unnecessary
        technical terminology.
        - Do not present predictions of fish activity as guarantees.
        """


        client = OpenAI(api_key=api_key)
        with client.beta.agents.sessions.create(
            agent_id=agent_key,
            environment={"type": "none"},
            input=prompt,
            stream=True,
        ).with_result_collection() as stream:
            root_turn_id = None
            final_items: set[str] = set()
            commentary_items: set[str] = set()
            parts: dict[tuple[int, int], str] = {}
            activity_parts: dict[tuple[str, int], str] = {}
            started = time.monotonic()
            stages: dict[str, float] = {}
            answer_deltas = 0
            _record_reasoning_step(evaluation_id, 0, "evaluation started")
            for event in stream:
                elapsed = round(time.monotonic() - started, 1)
                if event.type == "agent.session.turn.item.added":
                    item_kind = getattr(event.item, "phase", None) or event.item.type
                    stages.setdefault(f"{event.item.type}:{item_kind}", elapsed)
                    _record_reasoning_step(evaluation_id, elapsed, f"item added: {event.item.type}:{item_kind}")
                    if (
                        event.item.type == "message"
                        and event.item.role == "assistant"
                        and event.item.phase == "commentary"
                        and event.item.id is not None
                    ):
                        commentary_items.add(event.item.id)
                elif (
                    event.type == "agent.session.turn.reasoning_summary_text.done"
                    and event.turn_id in (None, root_turn_id)
                ):
                    _record_reasoning_step(evaluation_id, elapsed, "reasoning step", event.text)
                elif (
                    event.type == "agent.session.turn.output_text.done"
                    and event.item_id in commentary_items
                    and event.turn_id in (None, root_turn_id)
                ):
                    _record_reasoning_step(evaluation_id, elapsed, "commentary", event.text)
                elif (
                    event.type == "agent.session.turn.reasoning_summary_text.delta"
                    and event.turn_id in (None, root_turn_id)
                ):
                    key = (event.item_id, event.summary_index)
                    activity_parts[key] = activity_parts.get(key, "") + event.delta
                    job["ai_activity"] = activity_parts[key]
                    stages.setdefault("reasoning_summary_text", elapsed)
                    _notify_evaluation_waiters(evaluation_id)
                elif (
                    event.type == "agent.session.turn.output_text.delta"
                    and event.item_id in commentary_items
                    and event.turn_id in (None, root_turn_id)
                ):
                    key = (event.item_id, event.content_index)
                    activity_parts[key] = activity_parts.get(key, "") + event.delta
                    job["ai_activity"] = activity_parts[key]
                    stages.setdefault("commentary_text", elapsed)
                    _notify_evaluation_waiters(evaluation_id)
                elif (
                    event.type == "agent.session.turn.output_text.delta"
                    and event.item_id in final_items
                ):
                    answer_deltas += 1
                    stages.setdefault("answer_text_first", elapsed)
                    stages["answer_text_last"] = elapsed
                    job["ai_activity"] = None
                if event.type == "agent.session.turn.created" and event.turn.subagent_id is None:
                    root_turn_id = event.turn.id
                elif (
                    event.type == "agent.session.turn.item.added"
                    and root_turn_id is not None
                    and event.item.type == "message"
                    and event.item.turn_id == root_turn_id
                    and event.item.role == "assistant"
                    and event.item.phase == "final_answer"
                    and event.item.id is not None
                ):
                    final_items.add(event.item.id)
                elif (
                    event.type in (
                        "agent.session.turn.output_text.delta",
                        "agent.session.turn.output_text.done",
                    )
                    and root_turn_id is not None
                    and event.turn_id in (None, root_turn_id)
                    and event.item_id in final_items
                ):
                    key = (event.output_index, event.content_index)
                    if event.type == "agent.session.turn.output_text.delta":
                        parts[key] = parts.get(key, "") + event.delta
                    else:
                        parts[key] = event.text
                    job["ai_evaluation"] = "".join(parts[index] for index in sorted(parts))
                    _notify_evaluation_waiters(evaluation_id)
                elif (
                    event.type == "agent.session.turn.item.done"
                    and root_turn_id is not None
                    and event.item.type == "message"
                    and event.item.turn_id == root_turn_id
                    and event.item.role == "assistant"
                    and event.item.phase != "commentary"
                    and event.item.status == "completed"
                ):
                    for index, content in enumerate(event.item.content):
                        if content.type == "output_text":
                            parts[(event.output_index, index)] = content.text
                    job["ai_evaluation"] = "".join(parts[index] for index in sorted(parts))
                    _notify_evaluation_waiters(evaluation_id)
                if (
                    event.type in (
                        "agent.session.turn.completed",
                        "agent.session.turn.failed",
                        "agent.session.turn.cancelled",
                    )
                    and root_turn_id is not None
                    and event.turn_id == root_turn_id
                ) or event.type in ("agent.session.requires_action", "agent.session.failed"):
                    break
            result = stream.get_final_result()
            logger.warning(
                "AI evaluation timing in seconds: %s; answer text events: %d; total: %.1f",
                stages, answer_deltas, time.monotonic() - started,
            )
        job.update(status="completed", ai_evaluation=result.output_text, ai_activity=None)
        _notify_evaluation_waiters(evaluation_id)
    except Exception as exc:
        logger.exception("AI evaluation failed for job %s.", evaluation_id)
        job.update(status="failed", error=f"AI evaluation unavailable: {exc}", ai_activity=None)
        _notify_evaluation_waiters(evaluation_id)
