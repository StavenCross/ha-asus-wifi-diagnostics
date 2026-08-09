"""Shared entities for ASUS Wi-Fi Diagnostics."""

from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import AsusWifiDiagnosticsCoordinator
from .models import MeshNode


class AsusWifiDiagnosticsEntity(CoordinatorEntity[AsusWifiDiagnosticsCoordinator]):
    """Base entity associated with an AiMesh node."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AsusWifiDiagnosticsCoordinator, node: MeshNode) -> None:
        super().__init__(coordinator)
        self.node = node
        self._attr_unique_id = f"{node.mac}_2ghz_{self.entity_description.key}"
        # AsusRouter identifies AiMesh nodes with (asusrouter, MAC). Including
        # that identifier merges these diagnostics onto the existing device and
        # preserves its room, while our own identifier keeps this integration
        # standalone when AsusRouter isn't installed.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, node.mac), ("asusrouter", node.mac)},
            manufacturer=MANUFACTURER,
            model=node.model,
            name=node.display_name,
            configuration_url=f"http://{node.host}",
        )

    @property
    def available(self) -> bool:
        """Return whether this node was present in the latest snapshot."""
        return super().available and self.coordinator.snapshot_for(self.node.mac) is not None

