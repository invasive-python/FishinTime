import os
from datetime import datetime
from pathlib import Path

import boto3
import requests
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request
from openai import OpenAI, OpenAIError

import services.forecast_service as forecast_service

from models.weather_schemas import ForecastResponse

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

router = APIRouter()


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
    except (BotoCoreError, ClientError) as exc:
        raise SecretsManagerError(
            f"Could not retrieve secret '{secret_name}' from AWS Secrets Manager."
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
    request: Request, city: str, state: str, date: str
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

        api_key = request.app.state.openai_api_key
        prompt = f"""Using the information this JSON: {forecast.model_dump_json()}
                make a judgment as to whether or not it is a good time to go fishing
                from the surf or in a boat.
                """;

        try:
            client = OpenAI(api_key=api_key)
            with client.beta.agents.sessions.create(
                agent_id=request.app.state.openai_agent_id,
                environment={"type": "none"},
                input=prompt,
                stream=True,
            ).with_result_collection() as stream:
                result = stream.get_final_result()
                forecast.ai_evaluation = result.output_text
        except OpenAIError as exc:
            forecast.ai_evaluation = f"AI evaluation unavailable: {exc}"

        print(forecast.ai_evaluation)
        return forecast

    except HTTPException:
        raise
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"External provider request or response failed: {exc}",
        ) from exc 
