from datetime import date, datetime

from pydantic import BaseModel


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


class ForecastResponse(BaseModel):
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
    detailed_forecast: str
    ai_evaluation: str
