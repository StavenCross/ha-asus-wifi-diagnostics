"""Regression coverage for confirmed-client association lookups."""

from custom_components.asus_wifi_diagnostics.association import find_association
from custom_components.asus_wifi_diagnostics.models import (
    ChannelStats,
    MeshNode,
    NetworkSnapshot,
    NodeSnapshot,
    StationStats,
)


def test_association_for_finds_confirmed_mac_across_nodes() -> None:
    """A client lookup returns its live node and does not infer an absent station."""
    node = MeshNode(model="GT10", host="192.168.50.184", mac="AA:BB:CC:DD:EE:FF")
    station = StationStats(mac="24:E5:0F:D5:11:11", ip="192.168.50.40", rssi=-52)
    snapshot = NodeSnapshot(
        node=node,
        channel=ChannelStats(48, 1, 1, 1, 1, 1, -90, 95, 5),
        stations=(station,),
    )
    network = NetworkSnapshot(nodes={node.snapshot_key: snapshot})

    assert find_association(network, station.mac) == (node, station)
    assert find_association(network, "00:00:00:00:00:00") is None
