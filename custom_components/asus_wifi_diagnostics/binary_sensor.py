"""Binary sensor platform for ASUS Wi-Fi Diagnostics."""

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
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
        return {"threshold": self.threshold}

