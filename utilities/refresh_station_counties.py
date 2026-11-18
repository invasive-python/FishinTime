"""Refresh the precomputed NOAA station-to-Census-county lookup."""

import csv
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

from services.noaa_station_service import get_stations

CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinatesbatch"
COUNTY_GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "{year}_Gazetteer/{year}_Gaz_counties_national.zip"
)
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "services" / "station_counties.json"


def refresh_station_counties() -> None:
    stations = get_stations()
    coordinates = io.StringIO(newline="")
    writer = csv.writer(coordinates)
    records = {}
    for station in stations:
        station_id = station["id"]
        lat = station["lat"]
        lng = station["lng"]
        state = station["state"]
        if (
            not isinstance(station_id, str)
            or not isinstance(lat, (int, float))
            or not isinstance(lng, (int, float))
            or not isinstance(state, str)
            or station_id in records
        ):
            raise ValueError(f"Invalid NOAA station record: {station_id!r}")
        records[station_id] = {"lat": lat, "lng": lng, "state": state, "county": None}
        writer.writerow((station_id, lng, lat))

    if not records:
        raise ValueError("NOAA returned no stations.")

    counties = {}
    for year, delimiter in ((2026, "|"), (2020, "\t")):
        response = requests.get(COUNTY_GAZETTEER_URL.format(year=year), timeout=30)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            with archive.open(f"{year}_Gaz_counties_national.txt") as county_file:
                reader = csv.DictReader(
                    io.TextIOWrapper(county_file, encoding="utf-8-sig"),
                    delimiter=delimiter,
                )
                counties.update(
                    {row["GEOID"]: (row["USPS"], row["NAME"]) for row in reader}
                )

    response = requests.post(
        CENSUS_BATCH_URL,
        files={"coordinatesFile": ("stations.csv", coordinates.getvalue(), "text/csv")},
        data={"benchmark": "Public_AR_Current", "vintage": "Current_Current"},
        timeout=180,
    )
    response.raise_for_status()
    seen = set()
    for row in csv.reader(io.StringIO(response.text)):
        if len(row) < 4 or row[0] not in records or row[0] in seen:
            raise ValueError(f"Invalid Census batch response row: {row!r}")
        station_id, _, _, status = row[:4]
        if (
            float(row[1]) != records[station_id]["lng"]
            or float(row[2]) != records[station_id]["lat"]
        ):
            raise ValueError(f"Census returned different coordinates for station {station_id}.")
        seen.add(station_id)
        if status == "No_Match":
            continue
        if status != "Match" or len(row) < 6:
            raise ValueError(f"Invalid Census batch response row: {row!r}")
        county = counties.get(row[4] + row[5])
        if county is None:
            print(
                f"County code not found for station {station_id}: {row[4:6]!r}",
                file=sys.stderr,
            )
            continue
        state, name = county
        if state == records[station_id]["state"]:
            records[station_id]["county"] = name
        elif records[station_id]["state"]:
            print(
                f"State mismatch for station {station_id}: "
                f"NOAA {records[station_id]['state']}, Census {state}",
                file=sys.stderr,
            )

    if seen != records.keys():
        raise ValueError(f"Census batch response missing {len(records.keys() - seen)} stations.")

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=OUTPUT_PATH.parent, delete=False
        ) as output:
            temporary_path = Path(output.name)
            json.dump(records, output, ensure_ascii=False, sort_keys=True, indent=2)
            output.write("\n")
        temporary_path.replace(OUTPUT_PATH)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    matched = sum(record["county"] is not None for record in records.values())
    print(f"Saved {matched} county matches for {len(records)} stations to {OUTPUT_PATH}.")


if __name__ == "__main__":
    refresh_station_counties()
