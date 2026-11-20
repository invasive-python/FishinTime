from datetime import date, datetime
from typing import Annotated

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, field_serializer


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


class PrecipitationCondition(BaseModel):
    weather: str
    coverage: str | None = None


class PrecipitationInterval(BaseModel):
    start_time: datetime
    end_time: datetime
    conditions: list[PrecipitationCondition]


class WeatherResponse(BaseModel):
    timezone: str
    date: date
    periods: list[ForecastPeriod]
    precipitation_intervals: list[PrecipitationInterval] = Field(default_factory=list)


class ObservationStation(BaseModel):
    station_id: str
    name: str | None = None
    latitude: float
    longitude: float
    distance_miles: float


class PressureTrend(BaseModel):
    source: str | None = None
    station: ObservationStation | None = None
    observed_at: datetime | None = None
    current_pressure_inhg: float | None = None
    pressure_3_hours_ago_inhg: float | None = None
    change_3h_inhg: float | None = None
    trend: str | None = None
    outlook: str | None = None
    error: str | None = None


class WaterTemperatureObservation(BaseModel):
    source: str = "NOAA CO-OPS"
    station: ObservationStation | None = None
    observed_at: datetime | None = None
    temperature_f: float | None = None
    error: str | None = None


class DailyForecast(BaseModel):
    date: date
    precipitation_probability: int | None = None
    start_time: str | None = None
    temp: int | None = None
    wind_speed_max: float | None = None
    wind_speed_min: float | None = None
    wind_direction: str | None = None
    detailed_forecast: str | None = None
    moon_current_phase: str | None = None
    moon_closest_phase: str | None = None
    moon_closest_phase_date: str | None = None
    moon_brightness: str | None = None
    sunrise: str | None = None
    sunset: str | None = None
    moonrise: str | None = None
    moonset: str | None = None
    pressure: PressureTrend | None = None


class WeatherAlert(BaseModel):
    event: str
    severity: str | None = None
    urgency: str | None = None
    headline: str | None = None
    area: str | None = None
    onset: str | None = None
    ends: str | None = None
    description: str | None = None
    instruction: str | None = None


class ActiveAlerts(BaseModel):
    source: str = "NWS active alerts (api.weather.gov)"
    retrieved_at: str | None = None
    timezone: str | None = None
    coverage: str = (
        "Alerts covering the station location, its nearest marine forecast grid "
        "cell, and alerts naming the station's county. Alerts for adjacent marine "
        "zones, and surf-zone or coastal-waters forecast text, are not included."
    )
    items: list[WeatherAlert] = Field(default_factory=list)
    error: str | None = None


class StationForecastLocation(BaseModel):
    id: str
    name: str
    state: str
    lat: float
    lng: float
    county: str | None = None


class NearshoreGridLocation(BaseModel):
    office: str
    x: int
    y: int
    lat: float
    lng: float
    distance_km: float
    inferred: bool


class MarineForecastValue(BaseModel):
    valid_start: datetime
    duration: str
    value: float | None


class MarineForecastSeries(BaseModel):
    unit: str
    values: list[MarineForecastValue] = Field(default_factory=list)


class NearshoreForecast(BaseModel):
    source: str
    timezone: str
    forecast_days: int
    grid: NearshoreGridLocation
    wave_height: MarineForecastSeries
    wave_period: MarineForecastSeries
    wave_direction: MarineForecastSeries
    primary_swell_height: MarineForecastSeries
    primary_swell_period: MarineForecastSeries
    primary_swell_direction: MarineForecastSeries
    secondary_swell_height: MarineForecastSeries
    secondary_swell_period: MarineForecastSeries
    secondary_swell_direction: MarineForecastSeries
    wind_wave_height: MarineForecastSeries
    wind_wave_period: MarineForecastSeries
    wind_wave_direction: MarineForecastSeries
    wind_speed: MarineForecastSeries
    wind_direction: MarineForecastSeries


class ForecastResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    city: str
    city_lat: str
    city_long: str
    date: str
    precipitation_probability: int | None
    start_time: str | None
    temp: int | None
    water_temperature: WaterTemperatureObservation | None = None
    wind_speed_max: float | None
    wind_speed_min: float | None
    wind_direction: str | None
    moon_current_phase: str
    moon_closest_phase: str
    moon_closest_phase_date: str
    moon_brightness: str
    predictions: list[dict]
    station: StationForecastLocation | None = None
    forecast_start_date: date | None = None
    daily_forecasts: list[DailyForecast] = Field(default_factory=list)
    weather_forecast: list[ForecastPeriod] = Field(default_factory=list)
    precipitation_forecast: list[PrecipitationInterval] = Field(default_factory=list)
    nearshore: NearshoreForecast | None = None
    timezone: str | None = None
    alerts: ActiveAlerts | None = None
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
    detailed_forecast: str | None
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
    activity: str | None = None
    error: str | None = None
