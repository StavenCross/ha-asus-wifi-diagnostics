"""Tests for the read-only diagnostic report organizer."""

from datetime import UTC, datetime, timedelta

from tools.wifi_diagnostic_report import build_report, numeric_summary, render_markdown

START = datetime(2026, 8, 9, 15, tzinfo=UTC)
END = START + timedelta(hours=1)


def test_numeric_summary_ignores_non_numeric_states() -> None:
    summary = numeric_summary(
        [
            {"state": "10", "last_changed": START.isoformat()},
            {"state": "unavailable", "last_changed": START.isoformat()},
            {"state": "90", "last_changed": END.isoformat()},
        ]
    )
    assert summary == {
        "samples": 2,
        "latest": 90.0,
        "maximum": 90.0,
        "maximum_at": END.isoformat(),
        "minimum": 10.0,
        "minimum_at": START.isoformat(),
        "average": 50.0,
    }


def test_report_groups_metrics_and_incident_evidence() -> None:
    entity_id = "sensor.data_closet_utilization"
    states = [
        {
            "entity_id": entity_id,
            "state": "20",
            "attributes": {
                "diagnostic_key": "utilization",
                "node_mac": "AA:BB:CC:DD:EE:FF",
                "node_ip": "192.168.50.1",
                "friendly_name": "Data Closet 2.4 GHz utilization",
                "unit_of_measurement": "%",
            },
        },
        {
            "entity_id": "binary_sensor.gt6_internet",
            "state": "on",
            "attributes": {"friendly_name": "GT6 Internet"},
        },
    ]
    histories = [
        [
            {"entity_id": entity_id, "state": "20", "last_changed": START.isoformat()},
            {"entity_id": entity_id, "state": "95", "last_changed": END.isoformat()},
        ]
    ]
    incident_histories = [
        [
            {
                "entity_id": "event.data_closet_wifi_incident",
                "state": END.isoformat(),
                "attributes": {
                    "event_type": "high_utilization",
                    "event_types": ["high_utilization"],
                    "node_name": "Data Closet",
                    "top_clients": [{"mac": "11:22:33:44:55:66"}],
                },
            }
        ]
    ]
    report = build_report(states, histories, incident_histories, START, END)
    assert report["nodes"][0]["history"]["utilization"]["maximum"] == 95.0
    assert report["network_health"][0]["current"] == "on"
    assert report["incidents"][0]["evidence"]["top_clients"][0]["mac"] == (
        "11:22:33:44:55:66"
    )
    assert "high_utilization" in render_markdown(report)
