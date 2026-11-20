import unittest
from unittest.mock import Mock, patch

import requests

from services.nws_alerts_service import get_active_alerts, merge_active_alerts


def _feature(alert_id, event, severity, area, onset="2026-11-20T14:00:00+00:00",
             ends="2026-11-21T00:00:00+00:00"):
    return {
        "id": alert_id,
        "properties": {
            "event": event, "severity": severity, "areaDesc": area,
            "onset": onset, "ends": ends, "urgency": "Expected",
            "headline": f"{event} issued", "description": "Line one.\n\nLine   two.",
            "instruction": "Stay out of the water.",
        },
    }


def _response(features):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"features": features}
    return response


class NwsAlertsServiceTests(unittest.TestCase):
    @patch("services.nws_alerts_service.requests.get")
    def test_combines_point_and_county_alerts_in_station_local_time(self, get):
        advisory = _feature("a1", "Small Craft Advisory", "Minor", "Coastal waters")
        rip = _feature("r1", "Rip Current Statement", "Moderate", "Coastal Broward County")
        unrelated = _feature("u1", "Heat Advisory", "Minor", "Inland Palm Beach County")
        urgent = _feature("w1", "Flood Warning", "Severe", "Broward")

        def respond(_url, params, **_kwargs):
            if params.get("point") == "26.1883,-80.0933":
                return _response([advisory])
            if params.get("point") == "26.1858,-80.0842":
                return _response([advisory, urgent])
            return _response([rip, unrelated, advisory])

        get.side_effect = respond
        result = get_active_alerts(
            [(26.18829917907715, -80.09329986572266), (26.1858, -80.08425)],
            "FL", "Broward County", "America/New_York",
        )

        self.assertEqual(
            [alert.event for alert in result.items],
            ["Flood Warning", "Rip Current Statement", "Small Craft Advisory"],
        )
        self.assertEqual(result.timezone, "America/New_York")
        self.assertIsNone(result.error)
        alert = result.items[2]
        self.assertEqual((alert.onset, alert.ends), ("2026-11-20 09:00", "2026-11-20 19:00"))
        self.assertEqual(alert.description, "Line one. Line two.")
        queries = [call.kwargs["params"] for call in get.call_args_list]
        self.assertTrue(all(query["status"] == "actual" for query in queries))
        self.assertIn({"area": "FL", "status": "actual"}, queries)

    @patch("services.nws_alerts_service.requests.get")
    def test_merge_removes_duplicates_and_keeps_severity_order(self, get):
        get.return_value = _response([
            _feature("a1", "Small Craft Advisory", "Minor", "Waters"),
            _feature("w1", "Flood Warning", "Severe", "Broward"),
        ])
        first = get_active_alerts([(26.0, -80.0)], None, None, "America/New_York")
        get.return_value = _response([
            _feature("a2", "Small Craft Advisory", "Minor", "Waters"),
            _feature("r1", "Rip Current Statement", "Moderate", "Coast"),
        ])
        second = get_active_alerts([(26.1, -80.1)], None, None, "America/New_York")
        second.error = "partial"

        merged = merge_active_alerts(first, second)

        self.assertEqual(
            [alert.event for alert in merged.items],
            ["Flood Warning", "Rip Current Statement", "Small Craft Advisory"],
        )
        self.assertEqual(merged.error, "partial")
        self.assertEqual(len(first.items), 2)

    @patch("services.nws_alerts_service.requests.get")
    def test_county_alerts_are_not_requested_without_a_county(self, get):
        get.return_value = _response([])
        result = get_active_alerts([(40.0, -70.0)], "NY", None, "America/New_York")
        self.assertEqual(result.items, [])
        self.assertIsNone(result.error)
        self.assertEqual(get.call_count, 1)

    @patch("services.nws_alerts_service.requests.get")
    def test_partial_and_total_failures_are_reported_without_raising(self, get):
        def partial(_url, params, **_kwargs):
            if "area" in params:
                raise requests.ConnectionError("down")
            return _response([_feature("a1", "Small Craft Advisory", "Minor", "Waters")])

        get.side_effect = partial
        result = get_active_alerts([(26.0, -80.0)], "FL", "Broward County", "America/New_York")
        self.assertEqual(len(result.items), 1)
        self.assertIn("may be incomplete", result.error)

        get.side_effect = requests.ConnectionError("down")
        result = get_active_alerts([(26.0, -80.0)], "FL", "Broward County", "America/New_York")
        self.assertEqual(result.items, [])
        self.assertIn("unavailable", result.error)


if __name__ == "__main__":
    unittest.main()
