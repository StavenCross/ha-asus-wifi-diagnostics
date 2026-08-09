"""Tests for sparse Wi-Fi incident detection."""

from datetime import UTC, datetime, timedelta

from custom_components.asus_wifi_diagnostics.incident import (
    IncidentTracker,
    build_incident_snapshot,
)
from custom_components.asus_wifi_diagnostics.models import (
    ChannelStats,
    MeshNode,
    NodeSnapshot,
    StationStats,
)

NOW = datetime(2026, 8, 9, 16, 0, tzinfo=UTC)
NODE = MeshNode(model="GT6", host="192.168.50.1", mac="10:7C:61:1D:82:90")


def snapshot(busy: int, uptime: int = 1000) -> NodeSnapshot:
    return NodeSnapshot(
        node=NODE,
        channel=ChannelStats(
            channel=11,
            tx=10,
            in_bss=5,
            obss=40,
            no_category=2,
            no_packet=3,
            noise=-91,
            idle=100 - busy,
            busy=busy,
            glitches=12,
            bad_plcp=2,
        ),
        stations=(
            StationStats(
                mac="AA:BB:CC:DD:EE:FF",
                ip="192.168.50.20",
                name="camera",
                rssi=-80,
                retry_percent_value=30.0,
                tx_failures=2,
            ),
        ),
        router_uptime_seconds=uptime,
    )


def test_high_utilization_requires_one_minute_and_emits_recovery() -> None:
    tracker = IncidentTracker(90)
    assert tracker.update(snapshot(95), NOW) == []
    assert tracker.update(snapshot(96), NOW + timedelta(seconds=30)) == []
    incidents = tracker.update(snapshot(97), NOW + timedelta(seconds=60))
    assert [incident.event_type for incident in incidents] == ["high_utilization"]
    assert incidents[0].data["top_clients"][0]["name"] == "camera"
    assert tracker.update(snapshot(92), NOW + timedelta(seconds=90)) == []
    incidents = tracker.update(snapshot(60), NOW + timedelta(seconds=120))
    assert [incident.event_type for incident in incidents] == ["utilization_recovered"]
    assert incidents[0].data["duration_seconds"] == 120


def test_reachability_and_reboot_events_are_sparse() -> None:
    tracker = IncidentTracker(90)
    assert tracker.update(snapshot(20, uptime=1000), NOW) == []
    assert [item.event_type for item in tracker.update(None, NOW + timedelta(seconds=30))] == [
        "node_unreachable"
    ]
    assert tracker.update(None, NOW + timedelta(seconds=60)) == []
    assert [
        item.event_type
        for item in tracker.update(snapshot(20, uptime=20), NOW + timedelta(seconds=90))
    ] == ["node_recovered"]
    assert [
        item.event_type
        for item in tracker.update(snapshot(20, uptime=5), NOW + timedelta(seconds=120))
    ] == []
    assert [
        item.event_type
        for item in tracker.update(snapshot(20, uptime=2000), NOW + timedelta(seconds=150))
    ] == []
    assert [
        item.event_type
        for item in tracker.update(snapshot(20, uptime=10), NOW + timedelta(seconds=180))
    ] == ["router_reboot"]


def test_incident_snapshot_is_bounded() -> None:
    evidence = build_incident_snapshot(snapshot(95), NOW)
    assert evidence["total_utilization"] == 95
    assert evidence["other_wifi_airtime"] == 40
    assert len(evidence["top_clients"]) == 1
