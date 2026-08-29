"""Three-state monitored-client evidence contract tests."""

from datetime import UTC, datetime

from custom_components.asus_wifi_diagnostics.const import (
    BAND_2_4_GHZ,
    BAND_5_GHZ,
    OBSERVER_PROFILE_IOT_AP,
    OBSERVER_PROFILE_MAIN_MESH,
)
from custom_components.asus_wifi_diagnostics.models import (
    ChannelStats,
    ClientPresenceState,
    MeshNode,
    MonitoredClient,
    NetworkSnapshot,
    NodeSnapshot,
    StationStats,
)
from custom_components.asus_wifi_diagnostics.presence import evaluate_client_presence

CLIENT = MonitoredClient(
    mac="24:E5:0F:D5:11:11",
    name="Pantry light",
    observer_profile=OBSERVER_PROFILE_IOT_AP,
    band=BAND_2_4_GHZ,
)
IOT_24 = MeshNode(
    model="XT8",
    host="192.168.50.168",
    mac="AA:BB:CC:DD:EE:01",
    radio_interface="eth4",
    station_interface="eth4",
    observer_profile=OBSERVER_PROFILE_IOT_AP,
)
IOT_5 = MeshNode(
    model="XT8",
    host="192.168.50.168",
    mac="AA:BB:CC:DD:EE:01",
    radio_interface="eth5",
    station_interface="eth5",
    band=BAND_5_GHZ,
    observer_profile=OBSERVER_PROFILE_IOT_AP,
)
IOT_24_PEER = MeshNode(
    model="XT8",
    host="192.168.50.169",
    mac="AA:BB:CC:DD:EE:03",
    radio_interface="eth4",
    station_interface="eth4",
    observer_profile=OBSERVER_PROFILE_IOT_AP,
)
MESH_24 = MeshNode(
    model="GT10",
    host="192.168.50.1",
    mac="AA:BB:CC:DD:EE:02",
    radio_interface="eth6",
    station_interface="eth6",
    observer_profile=OBSERVER_PROFILE_MAIN_MESH,
)
NOW = datetime(2026, 8, 29, 18, 0, tzinfo=UTC)
CHANNEL = ChannelStats(11, 1, 1, 1, 1, 1, -90, 95, 5)


def node_snapshot(node: MeshNode, stations=()) -> NodeSnapshot:
    """Build one successful radio observation for presence tests."""
    return NodeSnapshot(node=node, channel=CHANNEL, stations=tuple(stations))


def network(nodes: dict[str, NodeSnapshot], failures=None) -> NetworkSnapshot:
    """Build one attributable poll generation."""
    return NetworkSnapshot(
        nodes=nodes,
        failures=failures or {},
        generation=7,
        observed_at=NOW,
    )


def test_connected_wins_even_when_an_eligible_observer_failed() -> None:
    """A fresh mapped station is positive evidence despite incomplete corroboration."""
    station = StationStats(mac=CLIENT.mac, ip="192.168.50.144")
    snapshot = network(
        {IOT_24.snapshot_key: node_snapshot(IOT_24, (station,))},
        {IOT_24_PEER.snapshot_key: "CannotConnectError"},
    )

    result = evaluate_client_presence(CLIENT, [IOT_24, IOT_24_PEER], snapshot)

    assert result.state == ClientPresenceState.CONNECTED
    assert result.association == (IOT_24, station)
    assert result.failed_observers == (IOT_24_PEER.snapshot_key,)


def test_complete_current_absence_is_not_connected() -> None:
    """Every eligible current observer must answer before absence is publishable."""
    snapshot = network({IOT_24.snapshot_key: node_snapshot(IOT_24)})

    result = evaluate_client_presence(CLIENT, [IOT_24, IOT_5, MESH_24], snapshot)

    assert result.state == ClientPresenceState.NOT_CONNECTED
    assert result.failed_observers == ()
    assert result.eligible_observers == (IOT_24.snapshot_key,)


def test_failed_eligible_observer_makes_absence_unknown() -> None:
    """SSH or collection failure cannot be converted into client absence."""
    snapshot = network({}, {IOT_24.snapshot_key: "CannotConnectError"})

    result = evaluate_client_presence(CLIENT, [IOT_24], snapshot)

    assert result.state == ClientPresenceState.UNKNOWN
    assert result.failed_observers == (IOT_24.snapshot_key,)


def test_unrelated_mesh_failure_does_not_invalidate_iot_absence() -> None:
    """Observer profiles keep unrelated infrastructure outside the evidence quorum."""
    snapshot = network(
        {IOT_24.snapshot_key: node_snapshot(IOT_24)},
        {MESH_24.snapshot_key: "CannotConnectError"},
    )

    result = evaluate_client_presence(CLIENT, [IOT_24, MESH_24], snapshot)

    assert result.state == ClientPresenceState.NOT_CONNECTED


def test_missing_profile_configuration_is_unknown() -> None:
    """No eligible observer is a configuration gap, never proof of absence."""
    result = evaluate_client_presence(CLIENT, [MESH_24], network({}))

    assert result.state == ClientPresenceState.UNKNOWN
    assert result.eligible_observers == ()


def test_startup_without_snapshot_is_unknown() -> None:
    """Restored state never creates a synthetic negative before the first current poll."""
    result = evaluate_client_presence(CLIENT, [IOT_24], None)

    assert result.state == ClientPresenceState.UNKNOWN
    assert result.generation == 0
