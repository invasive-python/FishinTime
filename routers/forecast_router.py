import logging
import uuid
from datetime import date as date_type
from datetime import datetime
from typing import Annotated, Any

import requests
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
)
from openai import OpenAI

from billing.auth import get_optional_authenticated_user
from billing.router import has_active_subscription
from models.weather_schemas import EvaluationJobResponse, ForecastResponse
from services import forecast_service

router = APIRouter()
logger = logging.getLogger(__name__)


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
) -> ForecastResponse:
    try:
        if not is_today_or_future(date):
            raise HTTPException(status_code=400, detail="Date must be today or in the future.")

        forecast = forecast_service.serve_forecast(city, state, date)
        if forecast is None:
            raise HTTPException(
                status_code=404,
                detail=f"No forecast or NOAA tide station found for {city} on {date}.",
            )

        is_subscriber = False
        if user is not None:
            try:
                is_subscriber = has_active_subscription(str(user["id"]))
            except HTTPException as exc:
                if exc.status_code != 503:
                    raise
                logger.exception(
                    "Could not verify subscription; returning free forecast data."
                )

        if is_subscriber:
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
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"External provider request or response failed: {exc}",
        ) from exc 

@router.get(
    "/forecast/evaluation/{evaluation_id}",
    summary="Get the status and result of an AI fishing evaluation",
    tags=["get_forecast"],
    responses={404: {"description": "AI evaluation not found."}},
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
    if not has_active_subscription(str(user["id"])):
        raise HTTPException(
            status_code=403,
            detail="An active subscription is required for AI evaluations.",
        )
    return EvaluationJobResponse(
        status=job["status"],
        ai_evaluation=job.get("ai_evaluation"),
        error=job.get("error"),
    )


def get_evaluation(
    request: Request, forecast: ForecastResponse, evaluation_id: str
) -> None:
    job = request.app.state.evaluation_jobs[evaluation_id]
    try:
        if not has_active_subscription(job["user_id"]):
            job.update(
                status="failed",
                error="An active subscription is required for AI evaluations.",
            )
            return

        api_key = request.app.state.openai_api_key
        agent_key = request.app.state.openai_agent_id

        prompt = f"""Using the information this JSON: {forecast.model_dump_json()}
                make a judgment as to whether or not it is a good day to go fishing
                from the surf or in a boat, and report the ideal times to fish. If
                possible, return information about the species of fish currently
                being caught, or historically being caught at the selected time of year.
                Do not mention the JSON or any input other than the user-provided state,
                city and date.
                """;

        client = OpenAI(api_key=api_key)
        with client.beta.agents.sessions.create(
            agent_id=agent_key,
            environment={"type": "none"},
            input=prompt,
            stream=True,
        ).with_result_collection() as stream:
            result = stream.get_final_result()
        job.update(status="completed", ai_evaluation=result.output_text)
    except Exception as exc:
        logger.exception("AI evaluation failed for job %s.", evaluation_id)
        job.update(status="failed", error=f"AI evaluation unavailable: {exc}")
