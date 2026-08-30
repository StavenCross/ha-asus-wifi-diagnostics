"""Pure AiMesh topology policy shared by the runtime and regression tests.

This boundary exists so a DHCP address movement can be distinguished from a real node outage
without importing Home Assistant or performing another network call. The coordinator remains the
sole owner of the one-shot rediscovery and retry lifecycle.
"""

from __future__ import annotations

from .models import MeshNode, NetworkSnapshot, NodeFailureKind


def node_locations(nodes: list[MeshNode]) -> dict[str, str]:
    """Project physical MAC-to-host topology without duplicate radio entries."""
    return {node.mac: node.host for node in nodes}


def rediscovery_needed(snapshot: NetworkSnapshot) -> bool:
    """Return true only for failures an address change can plausibly explain."""
    return any(
        evidence.kind in {NodeFailureKind.UNREACHABLE, NodeFailureKind.HOST_KEY_MISMATCH}
        for evidence in snapshot.failure_evidence.values()
    )


def topology_changed(previous: list[MeshNode], discovered: list[MeshNode]) -> bool:
    """Return whether rediscovery moved at least one stable physical MAC to another host."""
    return node_locations(previous) != node_locations(discovered)
