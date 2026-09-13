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
from .const import BAND_2_4_GHZ, BAND_5_GHZ, CONF_CRITICAL_UTILIZATION, DEFAULT_CRITICAL_UTILIZATION
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

NETWORK_HEALTH_DESCRIPTIONS = (
    BinarySensorEntityDescription(
        key="lan_reachability",
        translation_key="lan_reachability",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="router_dns",
        translation_key="router_dns",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="direct_dns",
        translation_key="direct_dns",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AsusWifiDiagnosticsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up congestion sensors."""
    coordinator = entry.runtime_data
    threshold = entry.options.get(
        CONF_CRITICAL_UTILIZATION,
        entry.data.get(CONF_CRITICAL_UTILIZATION, DEFAULT_CRITICAL_UTILIZATION),
    )
    async_add_entities(
        AsusWifiCongestionSensor(coordinator, node, threshold) for node in coordinator.nodes
    )
    async_add_entities(
        AsusWifiReachabilitySensor(coordinator, node)
        for node in coordinator.nodes
        if node.band == BAND_2_4_GHZ
    )
    controller = next(
        (node for node in coordinator.nodes if node.is_controller and node.band == BAND_2_4_GHZ),
        None,
    )
    if controller is not None:
        async_add_entities(
            AsusNetworkHealthSensor(coordinator, controller, description)
            for description in NETWORK_HEALTH_DESCRIPTIONS
        )


class AsusWifiCongestionSensor(AsusWifiDiagnosticsEntity, BinarySensorEntity):
    """Indicate when an individual 2.4 GHz radio is critically busy."""

    entity_description = DESCRIPTION

    def __init__(self, coordinator, node, threshold: int) -> None:
        self.threshold = threshold
        super().__init__(coordinator, node)
        if node.band == BAND_5_GHZ:
            self._attr_translation_key = None
            self._attr_name = "5 GHz congested"

    @property
    def is_on(self) -> bool | None:
        """Return congestion state."""
        snapshot = self.coordinator.snapshot_for(self.node)
        return snapshot.channel.busy >= self.threshold if snapshot else None

    @property
    def extra_state_attributes(self):
        """Return the threshold used."""
        return {
            "diagnostic_key": self.entity_description.key,
            "node_name": self.node.display_name,
            "node_mac": self.node.mac,
            "band": self.node.band_name,
            "node_ip": self.node.host,
            "threshold": self.threshold,
        }


class AsusWifiReachabilitySensor(AsusWifiDiagnosticsEntity, BinarySensorEntity):
    """Publish transport reachability without converting SSH trust into a LAN outage."""

    entity_description = REACHABLE_DESCRIPTION

    @property
    def available(self) -> bool:
        """Remain available so an unreachable node is represented as off."""
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool | None:
        """Return network connectivity independently from collection health."""
        if self.coordinator.snapshot_for(self.node) is not None:
            return True
        evidence = self.coordinator.failure_evidence_for(self.node)
        return evidence.transport_reachable if evidence else None

    @property
    def extra_state_attributes(self):
        """Return last-success and bounded failure evidence."""
        last_success = self.coordinator.last_node_success.get(self.node.snapshot_key)
        evidence = self.coordinator.failure_evidence_for(self.node)
        connected = self.is_on
        return {
            "diagnostic_key": self.entity_description.key,
            "node_name": self.node.display_name,
            "node_mac": self.node.mac,
            "node_ip": self.node.host,
            "last_successful_poll": last_success.isoformat() if last_success else None,
            "failure": self.coordinator.failure_for(self.node),
            "failure_kind": evidence.kind.value if evidence else None,
            "connectivity_state": (
                "connected"
                if connected is True
                else "unreachable"
                if connected is False
                else "unknown"
            ),
            "outage_eligible": evidence.outage_eligible if evidence else False,
            "diagnostic_status": "healthy" if evidence is None else "fault",
        }


class AsusNetworkHealthSensor(AsusWifiDiagnosticsEntity, BinarySensorEntity):
    """Expose one independent network-layer check on the controller device."""

    def __init__(self, coordinator, node, description: BinarySensorEntityDescription) -> None:
        self.entity_description = description
        super().__init__(coordinator, node)

    @property
    def available(self) -> bool:
        """Remain available independently of the radio collection outcome."""
        return self.coordinator.data is not None and self.entity_description.key in (
            self.coordinator.data.health
        )

    @property
    def is_on(self) -> bool | None:
        """Return whether the selected layer completed its bounded probe."""
        probe = self.coordinator.data.health.get(self.entity_description.key)
        return probe.healthy if probe else None

    @property
    def extra_state_attributes(self):
        """Publish latency, target, and a bounded failure class for incident correlation."""
        probe = self.coordinator.data.health.get(self.entity_description.key)
        if probe is None:
            return {}
        return {
            "diagnostic_key": probe.key,
            "target": probe.target,
            "latency_ms": probe.latency_ms,
            "failure": probe.failure,
        }
