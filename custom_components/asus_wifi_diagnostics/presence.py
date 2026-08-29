"""Evaluate router-side client presence without inferring device power.

This pure policy boundary distinguishes a complete absence observation from an incomplete router
poll. Consumers such as Govee State Monitoring may fuse the result with other evidence, but this
integration never turns router absence into fixture or mains-power state.
"""

from __future__ import annotations

from collections.abc import Iterable

from .const import CLIENT_BAND_ANY, OBSERVER_PROFILE_ALL
from .models import (
    ClientPresenceObservation,
    ClientPresenceState,
    MeshNode,
    MonitoredClient,
    NetworkSnapshot,
)


def _eligible_nodes(client: MonitoredClient, nodes: Iterable[MeshNode]) -> list[MeshNode]:
    """Return the exact current observers configured to judge one client."""
    return [
        node
        for node in nodes
        if (
            client.observer_profile == OBSERVER_PROFILE_ALL
            or node.observer_profile == client.observer_profile
        )
        and (client.band == CLIENT_BAND_ANY or node.band == client.band)
    ]


def evaluate_client_presence(
    client: MonitoredClient,
    expected_nodes: Iterable[MeshNode],
    snapshot: NetworkSnapshot | None,
) -> ClientPresenceObservation:
    """Classify one MAC from a single current poll generation.

    A positive association wins immediately. Absence is publishable only when every eligible radio
    returned a current snapshot. Missing configuration, startup, or any eligible failure remains
    unknown so downstream consumers cannot mistake infrastructure loss for client loss.
    """
    eligible = _eligible_nodes(client, expected_nodes)
    eligible_keys = tuple(sorted(node.snapshot_key for node in eligible))
    if snapshot is None or not eligible:
        return ClientPresenceObservation(
            client=client,
            state=ClientPresenceState.UNKNOWN,
            generation=snapshot.generation if snapshot else 0,
            observed_at=snapshot.observed_at if snapshot else None,
            eligible_observers=eligible_keys,
            queried_observers=(),
            failed_observers=eligible_keys,
        )

    queried = tuple(sorted(key for key in eligible_keys if key in snapshot.nodes))
    failed = tuple(sorted(key for key in eligible_keys if key not in snapshot.nodes))
    for node in eligible:
        node_snapshot = snapshot.nodes.get(node.snapshot_key)
        if node_snapshot is None:
            continue
        station = next(
            (candidate for candidate in node_snapshot.stations if candidate.mac == client.mac),
            None,
        )
        if station is not None:
            return ClientPresenceObservation(
                client=client,
                state=ClientPresenceState.CONNECTED,
                generation=snapshot.generation,
                observed_at=snapshot.observed_at,
                eligible_observers=eligible_keys,
                queried_observers=queried,
                failed_observers=failed,
                association=(node, station),
            )

    return ClientPresenceObservation(
        client=client,
        state=(ClientPresenceState.UNKNOWN if failed else ClientPresenceState.NOT_CONNECTED),
        generation=snapshot.generation,
        observed_at=snapshot.observed_at,
        eligible_observers=eligible_keys,
        queried_observers=queried,
        failed_observers=failed,
    )
