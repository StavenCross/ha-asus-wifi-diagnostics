"""Regression tests for bounded topology rediscovery policy."""

from custom_components.asus_wifi_diagnostics.models import (
    MeshNode,
    NetworkSnapshot,
    NodeFailureEvidence,
    NodeFailureKind,
)
from custom_components.asus_wifi_diagnostics.topology import (
    rediscovery_needed,
    topology_changed,
)

OFFICE_MAC = "10:7C:61:1D:81:90"
LIVING_MAC = "E8:9C:25:8A:50:30"


def _node(mac: str, host: str) -> MeshNode:
    """Build one physical 2.4 GHz node for topology comparisons."""
    return MeshNode(
        model="GT10",
        host=host,
        mac=mac,
        radio_interface="eth6",
        station_interface="eth6",
    )


def test_2026_08_30_node_ip_swap_is_retryable_topology_change() -> None:
    """The Office/Living MAC-to-IP swap is discoverable without becoming LAN-loss evidence."""
    old_nodes = [_node(OFFICE_MAC, "192.168.50.186"), _node(LIVING_MAC, "192.168.50.184")]
    corrected_nodes = [
        _node(OFFICE_MAC, "192.168.50.184"),
        _node(LIVING_MAC, "192.168.50.186"),
    ]
    failed = NetworkSnapshot(
        nodes={},
        failure_evidence={
            mac: NodeFailureEvidence(
                kind=NodeFailureKind.HOST_KEY_MISMATCH,
                source_error="HostKeyMismatchError",
                transport_reachable=True,
                outage_eligible=False,
            )
            for mac in (OFFICE_MAC, LIVING_MAC)
        },
    )

    assert rediscovery_needed(failed) is True
    assert topology_changed(old_nodes, corrected_nodes) is True
    assert all(not evidence.outage_eligible for evidence in failed.failure_evidence.values())


def test_unchanged_topology_is_not_a_retryable_remap() -> None:
    """A rediscovery returning the same MAC-to-IP map must not trigger recollection."""
    nodes = [_node(OFFICE_MAC, "192.168.50.184")]

    assert topology_changed(nodes, list(nodes)) is False
