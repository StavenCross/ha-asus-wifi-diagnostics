"""Tests for bounded Wi-Fi probe payload validation."""

import pytest

from custom_components.asus_wifi_diagnostics.probe import (
    InvalidProbePayload,
    parse_probe_payload,
)


def test_probe_payload_is_normalized_sorted_and_deduplicated() -> None:
    payload = {
        "probe_id": "CouchCast",
        "name": "CouchCast PC",
        "interface": "wlp7s0",
        "collected_at": "2026-08-09T16:00:00+00:00",
        "networks": [
            {
                "ssid": "Neighbor",
                "bssid": "aa:bb:cc:dd:ee:ff",
                "channel": 6,
                "frequency_mhz": 2437,
                "signal_percent": 55,
                "security": "WPA2",
                "in_use": False,
            },
            {
                "ssid": "Duplicate",
                "bssid": "AA:BB:CC:DD:EE:FF",
                "channel": 6,
                "frequency_mhz": 2437,
                "signal_percent": 10,
                "security": "WPA2",
            },
        ],
    }
    report = parse_probe_payload(payload, "2026-08-09T16:00:01+00:00")
    assert report.probe_id == "couchcast"
    assert len(report.networks) == 1
    assert report.networks[0].bssid == "AA:BB:CC:DD:EE:FF"
    assert report.networks[0].signal_percent == 55


def test_probe_payload_rejects_invalid_bssid() -> None:
    with pytest.raises(InvalidProbePayload):
        parse_probe_payload(
            {
                "probe_id": "couchcast",
                "name": "CouchCast PC",
                "interface": "wlp7s0",
                "collected_at": "now",
                "networks": [
                    {
                        "ssid": "bad",
                        "bssid": "not-a-mac",
                        "channel": 1,
                        "frequency_mhz": 2412,
                        "signal_percent": 50,
                        "security": "WPA2",
                    }
                ],
            },
            "now",
        )
