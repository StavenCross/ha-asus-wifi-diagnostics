"""Binary sensor platform for ASUS Wi-Fi Diagnostics."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AsusWifiDiagnosticsConfigEntry
from .const import CONF_CRITICAL_UTILIZATION, DEFAULT_CRITICAL_UTILIZATION
from .entity import AsusWifiDiagnosticsEntity

DESCRIPTION = BinarySensorEntityDescription(
    key="congested",
    translation_key="congested",
    icon="mdi:wifi-alert",
)

REACHABLE_DESCRIPTION = BinarySensorEntityDescription(
    key="reachable",
    translation_key="reachable",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AsusWifiDiagnosticsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up congestion sensors."""
    coordinator = entry.runtime_data
    threshold = entry.data.get(CONF_CRITICAL_UTILIZATION, DEFAULT_CRITICAL_UTILIZATION)
    async_add_entities(
        AsusWifiCongestionSensor(coordinator, node, threshold)
        for node in coordinator.nodes
    )
    async_add_entities(AsusWifiReachabilitySensor(coordinator, node) for node in coordinator.nodes)


class AsusWifiCongestionSensor(AsusWifiDiagnosticsEntity, BinarySensorEntity):
    """Indicate when an individual 2.4 GHz radio is critically busy."""

    entity_description = DESCRIPTION

    def __init__(self, coordinator, node, threshold: int) -> None:
        self.threshold = threshold
        super().__init__(coordinator, node)

    @property
    def is_on(self) -> bool | None:
        """Return congestion state."""
        snapshot = self.coordinator.snapshot_for(self.node.mac)
        return snapshot.channel.busy >= self.threshold if snapshot else None

    @property
    def extra_state_attributes(self):
        """Return the threshold used."""
        return {
            "diagnostic_key": self.entity_description.key,
            "node_name": self.node.display_name,
            "node_mac": self.node.mac,
            "node_ip": self.node.host,
            "threshold": self.threshold,
        }


class AsusWifiReachabilitySensor(AsusWifiDiagnosticsEntity, BinarySensorEntity):
    """Record whether an AiMesh node answered the latest bounded poll."""

    entity_description = REACHABLE_DESCRIPTION

    @property
    def available(self) -> bool:
        """Remain available so an unreachable node is represented as off."""
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        """Return whether the node supplied a current snapshot."""
        return self.coordinator.snapshot_for(self.node.mac) is not None

    @property
    def extra_state_attributes(self):
        """Return last-success and bounded failure evidence."""
        last_success = self.coordinator.last_node_success.get(self.node.mac)
        return {
            "diagnostic_key": self.entity_description.key,
            "node_name": self.node.display_name,
            "node_mac": self.node.mac,
            "node_ip": self.node.host,
            "last_successful_poll": last_success.isoformat() if last_success else None,
            "failure": self.coordinator.failure_for(self.node.mac),
        }
