import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from models.weather_schemas import ActiveAlerts, WeatherAlert
from services.weather_service import NWS_HEADERS

NWS_ALERTS_URL = "https://api.weather.gov/alerts/active"
_SEVERITY_ORDER = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3}
_MAX_ALERTS = 12
_MAX_DESCRIPTION = 600
_MAX_INSTRUCTION = 300
_COUNTY_SUFFIX = re.compile(
    r"\s+(county|parish|borough|census area|municipality|city and borough)$", re.I
)


def _fetch_alert_features(params: dict[str, str]) -> list[dict]:
    response = requests.get(
        NWS_ALERTS_URL,
        params={**params, "status": "actual"},
        headers=NWS_HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    features = data.get("features") if isinstance(data, dict) else None
    if not isinstance(features, list):
        raise ValueError("NWS alerts response is missing its features list.")
    return [feature for feature in features if isinstance(feature, dict)]


def _local_time(value: object, zone: ZoneInfo) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone(zone).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _trim(value: object, limit: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _names_county(area_description: object, county: str) -> bool:
    name = _COUNTY_SUFFIX.sub("", county.strip())
    return bool(name) and isinstance(area_description, str) and bool(
        re.search(rf"\b{re.escape(name)}\b", area_description, re.I)
    )


def merge_active_alerts(first: ActiveAlerts, second: ActiveAlerts) -> ActiveAlerts:
    seen = set()
    items = []
    for alert in [*first.items, *second.items]:
        key = (alert.event, alert.onset, alert.ends, alert.area)
        if key not in seen:
            seen.add(key)
            items.append(alert)
    items.sort(key=lambda alert: (_SEVERITY_ORDER.get(alert.severity, 4), alert.onset or ""))
    return first.model_copy(update={
        "items": items[:_MAX_ALERTS],
        "error": first.error or second.error,
    })


def get_active_alerts(
    points: list[tuple[float, float]],
    state: str | None,
    county: str | None,
    timezone: str,
) -> ActiveAlerts:
    zone = ZoneInfo(timezone)
    # The NWS API accepts at most four decimal places for a point.
    queries: list[tuple[dict[str, str], bool]] = [
        ({"point": f"{lat:.4f},{lng:.4f}"}, False) for lat, lng in points
    ]
    if state and county:
        queries.append(({"area": state}, True))

    results: list[tuple[list[dict], bool] | Exception] = []
    with ThreadPoolExecutor(max_workers=max(1, len(queries))) as executor:
        futures = [executor.submit(_fetch_alert_features, params) for params, _ in queries]
        for future, (_, county_only) in zip(futures, queries):
            try:
                results.append((future.result(), county_only))
            except (requests.RequestException, ValueError) as exc:
                results.append(exc)

    summary = ActiveAlerts(
        retrieved_at=datetime.now(zone).strftime("%Y-%m-%d %H:%M"), timezone=timezone
    )
    failures = [result for result in results if isinstance(result, Exception)]
    if failures:
        summary.error = (
            "NWS alerts are unavailable; no alert information could be checked."
            if len(failures) == len(results)
            else "Some NWS alert queries failed, so this alert list may be incomplete."
        )

    alerts: dict[str, dict] = {}
    for result in results:
        if isinstance(result, Exception):
            continue
        features, county_only = result
        for feature in features:
            properties = feature.get("properties")
            if not isinstance(properties, dict) or not properties.get("event"):
                continue
            if county_only and not _names_county(properties.get("areaDesc"), county or ""):
                continue
            alerts.setdefault(str(feature.get("id") or properties.get("id")), properties)

    ordered = sorted(
        alerts.values(),
        key=lambda item: (
            _SEVERITY_ORDER.get(item.get("severity"), 4), str(item.get("onset") or ""),
        ),
    )
    summary.items = [
        WeatherAlert(
            event=item["event"],
            severity=item.get("severity"),
            urgency=item.get("urgency"),
            headline=item.get("headline"),
            area=_trim(item.get("areaDesc"), 200),
            onset=_local_time(item.get("onset") or item.get("effective"), zone),
            ends=_local_time(item.get("ends") or item.get("expires"), zone),
            description=_trim(item.get("description"), _MAX_DESCRIPTION),
            instruction=_trim(item.get("instruction"), _MAX_INSTRUCTION),
        )
        for item in ordered[:_MAX_ALERTS]
    ]
    return summary
