"""Event platform for durable Wi-Fi incident snapshots."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import AsusWifiDiagnosticsConfigEntry
from .const import CONF_CRITICAL_UTILIZATION, DEFAULT_CRITICAL_UTILIZATION
from .coordinator import AsusWifiDiagnosticsCoordinator
from .entity import device_info_for
from .incident import IncidentTracker
from .models import MeshNode

EVENT_TYPES = [
    "high_utilization",
    "utilization_recovered",
    "node_unreachable",
    "node_recovered",
    "router_reboot",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AsusWifiDiagnosticsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up recorder-backed incident event entities."""
    threshold = entry.data.get(CONF_CRITICAL_UTILIZATION, DEFAULT_CRITICAL_UTILIZATION)
    async_add_entities(
        AsusWifiIncidentEvent(entry.runtime_data, node, threshold)
        for node in entry.runtime_data.nodes
    )


class AsusWifiIncidentEvent(CoordinatorEntity[AsusWifiDiagnosticsCoordinator], EventEntity):
    """Emit sparse evidence snapshots when radio health materially changes."""

    _attr_event_types = EVENT_TYPES
    _attr_has_entity_name = True
    _attr_icon = "mdi:timeline-alert"
    _attr_translation_key = "incident"

    def __init__(
        self,
        coordinator: AsusWifiDiagnosticsCoordinator,
        node: MeshNode,
        threshold: int,
    ) -> None:
        super().__init__(coordinator)
        self.node = node
        self._tracker = IncidentTracker(threshold)
        self._attr_unique_id = f"{node.mac}_2ghz_incident"
        self._attr_device_info = device_info_for(node)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Translate coordinator snapshots into sparse recorder events."""
        snapshot = self.coordinator.snapshot_for(self.node.mac)
        node_area_id = self.coordinator.node_area_id(self.node.mac)
        for incident in self._tracker.update(snapshot, dt_util.utcnow()):
            top_clients = [
                {
                    **client,
                    **self.coordinator.ownership_for(
                        client.get("mac"),
                        client.get("ip"),
                        client.get("name"),
                        node_area_id,
                    ),
                }
                for client in incident.data.get("top_clients", [])
            ]
            data = {
                "diagnostic_key": "incident",
                "node_name": self.node.display_name,
                "node_mac": self.node.mac,
                "node_ip": self.node.host,
                **incident.data,
                "top_clients": top_clients,
            }
            probe = self.coordinator.data.probes.get("couchcast") if self.coordinator.data else None
            if probe:
                data["couchcast_probe_collected_at"] = probe.collected_at
                data["couchcast_visible_bssids"] = len(probe.networks)
            self._trigger_event(incident.event_type, data)
            self.async_write_ha_state()
