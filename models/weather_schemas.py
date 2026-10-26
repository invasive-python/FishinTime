from datetime import date, datetime
from typing import Annotated

import pandas as pd
from pydantic import BaseModel, ConfigDict, WithJsonSchema, field_serializer


class LocationRequest(BaseModel):
    state: str


class LocationResponse(BaseModel):
    state: str
    stations: list[dict]


class ForecastPeriod(BaseModel):
    name: str
    start_time: datetime
    end_time: datetime
    temperature: float | None = None
    temperature_unit: str | None = None
    wind_speed: dict | None = None
    wind_direction: str | None = None
    precipitation_probability: int | None = None
    detailed_forecast: str | None = None


class WeatherResponse(BaseModel):
    city: str
    date: date
    periods: list[ForecastPeriod]


class PressureTrend(BaseModel):
    current_pressure_inhg: float | None = None
    pressure_3_hours_ago_inhg: float | None = None
    change_3h_inhg: float | None = None
    trend: str | None = None
    outlook: str | None = None
    error: str | None = None


class ForecastResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    city: str
    date: str
    precipitation_probability: int
    start_time: str
    temp: int
    wind_speed_max: float
    wind_speed_min: float
    wind_direction: str
    moon_current_phase: str
    moon_closest_phase: str
    moon_closest_phase_date: str
    moon_brightness: str
    predictions: list[dict]
    waves: Annotated[
        pd.DataFrame | None,
        WithJsonSchema(
            {
                "anyOf": [
                    {"type": "array", "items": {"type": "object"}},
                    {"type": "null"},
                ]
            }
        ),
    ] = None
    pressure: PressureTrend | None = None
    detailed_forecast: str
    ai_evaluation: str = ""
    evaluation_id: str | None = None

    @field_serializer("waves")
    def serialize_waves(
        self, value: pd.DataFrame | None
    ) -> list[dict[str, object]] | None:
        if value is None:
            return None
        records = value.to_dict(orient="records")
        return [
            {
                field: (
                    None
                    if item is None or pd.isna(item)
                    else item.isoformat()
                    if isinstance(item, pd.Timestamp)
                    else item.item()
                    if hasattr(item, "item")
                    else item
                )
                for field, item in record.items()
            }
            for record in records
        ]


class EvaluationJobResponse(BaseModel):
    status: str
    ai_evaluation: str | None = None
    error: str | None = None
