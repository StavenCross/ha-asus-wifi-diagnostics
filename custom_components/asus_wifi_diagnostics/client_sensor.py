"""Recorder-friendly monitored-client presence entities.

The entity preserves the v0.7 association unique ID while narrowing its public state to a versioned
three-value evidence contract. Router observations remain diagnostic and never claim device power.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import PRESENCE_CONTRACT_VERSION
from .coordinator import AsusWifiDiagnosticsCoordinator
from .models import ClientPresenceState, MonitoredClient


class ClientPresenceSensor(CoordinatorEntity[AsusWifiDiagnosticsCoordinator], SensorEntity):
    """Publish one monitored MAC as connected, not connected, or unknown."""

    _attr_icon = "mdi:wifi-marker"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = False
    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(
        self,
        coordinator: AsusWifiDiagnosticsCoordinator,
        entry_id: str,
        client: MonitoredClient,
    ) -> None:
        """Bind the stable entity identity to one normalized monitored-client record."""
        super().__init__(coordinator)
        self._attr_options = [state.value for state in ClientPresenceState]
        self._client = client
        ownership = (
            coordinator.ownership.by_device_id.get(client.ha_device_id)
            if client.ha_device_id
            else None
        )
        self._attr_name = f"{ownership.name if ownership else client.name} Wi-Fi association"
        self._attr_unique_id = (
            f"{entry_id}_client_association_{client.mac.replace(':', '').lower()}"
        )

    @property
    def native_value(self) -> str:
        """Return the versioned three-state evidence value for Recorder and consumers."""
        return self.coordinator.presence_for(self._client.mac).state.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose bounded provenance required to qualify this observation downstream."""
        observation = self.coordinator.presence_for(self._client.mac)
        base: dict[str, Any] = {
            "contract_version": PRESENCE_CONTRACT_VERSION,
            "client_mac": self._client.mac,
            "client_name": self._client.name,
            "ha_device_id": self._client.ha_device_id,
            "observer_profile": self._client.observer_profile,
            "expected_band": self._client.band,
            "poll_generation": observation.generation,
            "observed_at": (
                observation.observed_at.isoformat() if observation.observed_at else None
            ),
            "eligible_observers": list(observation.eligible_observers),
            "queried_observers": list(observation.queried_observers),
            "failed_observers": list(observation.failed_observers),
            "evidence_complete": (
                observation.state != ClientPresenceState.UNKNOWN
                and not observation.failed_observers
            ),
            "connected": observation.state == ClientPresenceState.CONNECTED,
            "last_connected_at": (
                self.coordinator.last_client_connected[self._client.mac].isoformat()
                if self._client.mac in self.coordinator.last_client_connected
                else None
            ),
        }
        if observation.association is None:
            return base
        node, station = observation.association
        return {
            **base,
            "node_name": node.display_name,
            "node_mac": node.mac,
            "node_ip": node.host,
            "band": node.band_name,
            "radio_interface": node.radio_interface,
            "ip": station.ip,
            "rssi": station.rssi,
            "noise": station.noise,
            "tx_rate_mbps": station.tx_rate_mbps,
            "rx_rate_mbps": station.rx_rate_mbps,
            "tx_retry_percent": station.retry_percent,
            "tx_failures": station.tx_failures,
        }
