from dataclasses import dataclass


@dataclass(frozen=True)
class Station:
    id: str
    name: str
    lat: float
    lng: float
    state: str
    county: str | None
