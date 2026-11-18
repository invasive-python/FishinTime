import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from services.station_county_service import get_station_county
from utilities.refresh_station_counties import refresh_station_counties


class StationCountyTests(unittest.TestCase):
    @patch("services.station_county_service._load_counties")
    def test_lookup_rejects_stale_coordinates_or_state(self, load_counties):
        load_counties.return_value = {
            "123": {"lat": 26.1, "lng": -80.1, "state": "FL", "county": "Broward County"}
        }
        station = {"id": "123", "lat": 26.1, "lng": -80.1, "state": "FL"}

        self.assertEqual(get_station_county(station), "Broward County")
        for field, value in (("lat", 26.2), ("lng", -80.2), ("state", "GA")):
            self.assertIsNone(get_station_county({**station, field: value}))
        self.assertIsNone(get_station_county({**station, "id": "missing"}))

    @patch("utilities.refresh_station_counties.requests.post")
    @patch("utilities.refresh_station_counties.requests.get")
    @patch("utilities.refresh_station_counties.get_stations")
    def test_refresh_matches_batch_results_by_station_id(self, get_stations, get, post):
        get_stations.return_value = [
            {"id": "first", "lat": 26.1, "lng": -80.1, "state": "FL"},
            {"id": "second", "lat": 27.1, "lng": -81.1, "state": "FL"},
        ]
        archives = []
        for year, delimiter in ((2026, "|"), (2020, "\t")):
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as archive:
                archive.writestr(
                    f"{year}_Gaz_counties_national.txt",
                    delimiter.join(("USPS", "GEOID", "NAME"))
                    + "\n"
                    + delimiter.join(("FL", "12011", "Broward County"))
                    + "\n",
                )
            archives.append(Mock(content=data.getvalue()))
        get.side_effect = archives
        post.return_value.text = (
            '"second","-81.1","27.1","No_Match"\n'
            '"first","-80.1","26.1","Match","12","011","042501","1017"\n'
        )

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "counties.json"
            with patch("utilities.refresh_station_counties.OUTPUT_PATH", output):
                refresh_station_counties()
            records = json.loads(output.read_text(encoding="utf-8"))
            post.return_value.text = '"first","-80.2","26.1","No_Match"\n'
            get.side_effect = archives
            with patch("utilities.refresh_station_counties.OUTPUT_PATH", output):
                with self.assertRaisesRegex(ValueError, "different coordinates"):
                    refresh_station_counties()
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), records)

        self.assertEqual(records["first"]["county"], "Broward County")
        self.assertIsNone(records["second"]["county"])
        self.assertIn("first,-80.1,26.1", post.call_args.kwargs["files"]["coordinatesFile"][1])

    @patch("utilities.refresh_station_counties.requests.post")
    @patch("utilities.refresh_station_counties.requests.get")
    @patch("utilities.refresh_station_counties.get_stations")
    def test_refresh_rejects_incomplete_batch(self, get_stations, get, post):
        get_stations.return_value = [
            {"id": "first", "lat": 26.1, "lng": -80.1, "state": "FL"}
        ]
        archives = []
        for year in (2026, 2020):
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as archive:
                archive.writestr(f"{year}_Gaz_counties_national.txt", "USPS|GEOID|NAME\n")
            archives.append(Mock(content=data.getvalue()))
        get.side_effect = archives
        post.return_value.text = ""

        with self.assertRaisesRegex(ValueError, "missing 1 stations"):
            refresh_station_counties()


if __name__ == "__main__":
    unittest.main()
