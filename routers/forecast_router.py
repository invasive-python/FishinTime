import json
import logging
import os
import uuid
from datetime import datetime

import boto3
import requests
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from openai import OpenAI

from models.weather_schemas import EvaluationJobResponse, ForecastResponse
from services import forecast_service

router = APIRouter()
logger = logging.getLogger(__name__)


class SecretsManagerError(RuntimeError):
    """Raised when the application cannot retrieve its configured secret."""


def get_secret(secret_name: str) -> str:
    region_name = (
        os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-2"
    )

    try:
        response = boto3.client(
            "secretsmanager", region_name=region_name
        ).get_secret_value(SecretId=secret_name)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "Unknown")
        raise SecretsManagerError(
            f"Could not retrieve secret '{secret_name}' from AWS Secrets Manager "
            f"in region '{region_name}' (AWS error: {error_code})."
        ) from exc
    except BotoCoreError as exc:
        raise SecretsManagerError(
            f"Could not retrieve secret '{secret_name}' from AWS Secrets Manager "
            f"in region '{region_name}' ({type(exc).__name__}). Check the AWS "
            "credentials and configuration available to this process."
        ) from exc

    secret_string = response.get("SecretString")
    if not isinstance(secret_string, str) or not secret_string.strip():
        raise SecretsManagerError(
            f"Secret '{secret_name}' must contain a non-empty SecretString."
        )
    return secret_string


def is_today_or_future(date_string: str, date_format: str = "%Y-%m-%d") -> bool:
    try:
        input_date = datetime.strptime(date_string, date_format).date()
        today = datetime.today().date()
        
        return input_date >= today
        
    except ValueError:
        return False

@router.get(
    "/forecast/get_forecast",
    response_model=ForecastResponse,
    summary="Get forecast periods for a city and date",
    tags=["get_forecast"],
)
def get_forecast(
    request: Request,
    background_tasks: BackgroundTasks,
    city: str,
    state: str,
    date: str,
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

        evaluation_id = str(uuid.uuid4())
        evaluation_jobs = getattr(request.app.state, "evaluation_jobs", None)
        if evaluation_jobs is None:
            evaluation_jobs = {}
            request.app.state.evaluation_jobs = evaluation_jobs
        evaluation_jobs[evaluation_id] = {"status": "pending"}
        background_tasks.add_task(
            get_evaluation, request, forecast, evaluation_id
        )
        forecast.evaluation_id = evaluation_id

        print(f"{forecast.city} Fishing Forecast for {forecast.date}:")
        print("----------------------")
        print("precipitation: " + str(forecast.precipitation_probability) + "% chance")
        print("precip.time: " + str(forecast.start_time))
        print("temperature: " + str(forecast.temp) + "°F")
        print("wind speed (max): " + str(forecast.wind_speed_max) + " mph")
        print("wind speed (min): " + str(forecast.wind_speed_min) + " mph")
        print("wind direction: " + forecast.wind_direction)
        print("current moon phase: " + forecast.moon_current_phase)
        print("next moon phase: (" + forecast.moon_closest_phase_date + ") " + forecast.moon_closest_phase)
        print("moon brightness: " + forecast.moon_brightness)
        print("tides: " + str(forecast.predictions))
        print("forecast: " + forecast.detailed_forecast)

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
    response_model=EvaluationJobResponse,
    summary="Get the status and result of an AI fishing evaluation",
    tags=["get_forecast"],
)
def get_evaluation_status(
    evaluation_id: str, request: Request
) -> EvaluationJobResponse:
    evaluation_jobs = getattr(request.app.state, "evaluation_jobs", {})
    job = evaluation_jobs.get(evaluation_id)
    if job is None:
        raise HTTPException(status_code=404, detail="AI evaluation not found.")
    return EvaluationJobResponse(**job)


def get_evaluation(
    request: Request, forecast: ForecastResponse, evaluation_id: str
) -> None:
    job = request.app.state.evaluation_jobs[evaluation_id]
    try:
        api_key = request.app.state.openai_api_key
        secret = json.loads(api_key)["OPENAI_API_KEY"]

        agent_key = request.app.state.openai_agent_id
        agent_secret = json.loads(agent_key)["AGENT_ID"]

        prompt = f"""Using the information this JSON: {forecast.model_dump_json()}
                make a judgment as to whether or not it is a good day to go fishing
                from the surf or in a boat, and report the ideal times to fish. If
                possible, return information about the species of fish currently
                being caught, or historically being caught at the selected time of year.
                Do not mention the JSON or any input other than the user-provided state,
                city and date.
                """;

        client = OpenAI(api_key=secret)
        with client.beta.agents.sessions.create(
            agent_id=agent_secret,
            environment={"type": "none"},
            input=prompt,
            stream=True,
        ).with_result_collection() as stream:
            result = stream.get_final_result()
        job.update(status="completed", ai_evaluation=result.output_text)
    except Exception as exc:
        logger.exception("AI evaluation failed for job %s.", evaluation_id)
        job.update(status="failed", error=f"AI evaluation unavailable: {exc}")
