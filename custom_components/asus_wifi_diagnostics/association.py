"""Pure router-client association lookup for recorder-backed diagnostics."""

from __future__ import annotations

from .models import MeshNode, NetworkSnapshot, StationStats


def find_association(
    snapshot: NetworkSnapshot | None, mac: str
) -> tuple[MeshNode, StationStats] | None:
    """Find one client MAC in the latest all-node station tables.

    The router is the authoritative association source.  This deliberately returns no result
    when the client is absent rather than inferring an association from a stale IP or room name.
    """
    if snapshot is None:
        return None
    target = mac.upper()
    for node_snapshot in snapshot.nodes.values():
        station = next((item for item in node_snapshot.stations if item.mac == target), None)
        if station is not None:
            return node_snapshot.node, station
    return None
