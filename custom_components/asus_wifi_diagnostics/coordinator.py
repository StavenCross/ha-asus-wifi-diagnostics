"""Update coordinator for ASUS Wi-Fi Diagnostics."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AsusWifiDiagnosticsApi, AsusWifiDiagnosticsError
from .association import find_association
from .const import DISCOVERY_INTERVAL, DOMAIN
from .models import (
    ClientPresenceState,
    MeshNode,
    MonitoredClient,
    NetworkSnapshot,
    NodeFailureEvidence,
    ProbeSnapshot,
    StationStats,
)
from .ownership import OwnershipIndex, build_ownership_index
from .presence import evaluate_client_presence
from .topology import rediscovery_needed, topology_changed

_LOGGER = logging.getLogger(__name__)


class AsusWifiDiagnosticsCoordinator(DataUpdateCoordinator[NetworkSnapshot]):
    """Coordinate low-impact polling across AiMesh nodes."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: AsusWifiDiagnosticsApi,
        update_interval: timedelta,
        manual_overrides: dict[str, str] | None = None,
        monitored_clients: dict[str, MonitoredClient] | None = None,
    ) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.api = api
        self.nodes: list[MeshNode] = []
        self._last_discovery: datetime | None = None
        self.last_node_success: dict[str, datetime] = {}
        self.webhook_id = ""
        self.manual_overrides = manual_overrides or {}
        self.monitored_clients = monitored_clients or {}
        self.last_client_connected: dict[str, datetime] = {}
        self.ownership = OwnershipIndex({}, {}, {})

    async def _async_update_data(self) -> NetworkSnapshot:
        now = dt_util.utcnow()
        try:
            self.ownership = build_ownership_index(self.hass)
            if (
                not self.nodes
                or self._last_discovery is None
                or now - self._last_discovery >= DISCOVERY_INTERVAL
            ):
                try:
                    discovered = await self.api.discover_nodes()
                except AsusWifiDiagnosticsError:
                    if not self.nodes:
                        raise
                    _LOGGER.warning("AiMesh rediscovery failed; polling the last known node set")
                else:
                    self.nodes = discovered
                self._last_discovery = now
            snapshot = await self.api.collect(self.nodes)
            if rediscovery_needed(snapshot):
                snapshot = await self._async_rediscover_changed_topology(snapshot, now)
            for snapshot_key in snapshot.nodes:
                self.last_node_success[snapshot_key] = now
            for mac, client in self.monitored_clients.items():
                observation = evaluate_client_presence(client, self.nodes, snapshot)
                if (
                    observation.state == ClientPresenceState.CONNECTED
                    and snapshot.observed_at is not None
                ):
                    self.last_client_connected[mac] = snapshot.observed_at
            if self.data and self.data.probes:
                snapshot = replace(snapshot, probes=self.data.probes)
            return snapshot
        except AsusWifiDiagnosticsError as err:
            raise UpdateFailed(str(err)) from err

    @callback
    def ownership_for(
        self,
        mac: str | None,
        ip: str | None,
        name: str | None = None,
        node_area_id: str | None = None,
    ) -> dict:
        """Return Home Assistant ownership attributes for a router client."""
        return self.ownership.resolve(
            mac,
            ip,
            self.manual_overrides,
            name=name,
            node_area_id=node_area_id,
        )

    @callback
    def node_area_id(self, mac: str) -> str | None:
        """Return the HA area assigned to an AiMesh node."""
        from homeassistant.helpers import device_registry as dr

        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, mac.lower())})
        return device.area_id if device else None

    @callback
    def snapshot_for(self, node: MeshNode | str):
        """Return a radio snapshot from current data."""
        key = node.snapshot_key if isinstance(node, MeshNode) else node
        return self.data.nodes.get(key) if self.data else None

    @callback
    def failure_for(self, node: MeshNode | str) -> str | None:
        """Return the bounded failure classification from the latest poll."""
        key = node.snapshot_key if isinstance(node, MeshNode) else node
        return self.data.failures.get(key) if self.data else None

    @callback
    def failure_evidence_for(self, node: MeshNode | str) -> NodeFailureEvidence | None:
        """Return the automation-safe failure semantics from the latest poll."""
        key = node.snapshot_key if isinstance(node, MeshNode) else node
        return self.data.failure_evidence.get(key) if self.data else None

    async def _async_rediscover_changed_topology(
        self, snapshot: NetworkSnapshot, now: datetime
    ) -> NetworkSnapshot:
        """Rediscover once and recollect only if stable MAC-to-IP topology changed.

        This is intentionally not a retry loop. Authentication, command, and unknown collection
        faults do not enter it, while an unchanged discovery returns the original evidence.
        """
        previous_nodes = self.nodes
        try:
            discovered = await self.api.discover_nodes()
        except AsusWifiDiagnosticsError as err:
            _LOGGER.warning("Failure-triggered AiMesh rediscovery failed: %s", err)
            return snapshot
        self._last_discovery = now
        if not topology_changed(previous_nodes, discovered):
            return snapshot
        _LOGGER.warning("AiMesh MAC-to-IP topology changed; retrying one diagnostic collection")
        self.nodes = discovered
        return await self.api.collect(self.nodes)

    @callback
    def association_for(self, mac: str) -> tuple[MeshNode, StationStats] | None:
        """Return the current router-observed association for one confirmed client MAC.

        Manual client mappings are deliberate operator confirmations.  Looking them up from
        every current node snapshot turns the router's transient station tables into a single,
        recorder-friendly observation without guessing ownership from an IP address or name.
        """
        return find_association(self.data, mac)

    @callback
    def presence_for(self, mac: str):
        """Return the typed current-generation observation for one enrolled client.

        Client sensors call this single boundary so association completeness, profile selection,
        and failure handling cannot drift between entity state and attributes.
        """
        client = self.monitored_clients[mac.upper()]
        return evaluate_client_presence(client, self.nodes, self.data)

    @callback
    def async_update_probe(self, report: ProbeSnapshot) -> None:
        """Store a probe report and notify entities immediately."""
        if self.data is None:
            return
        probes = {**self.data.probes, report.probe_id: report}
        self.async_set_updated_data(replace(self.data, probes=probes))
