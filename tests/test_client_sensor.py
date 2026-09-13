"""Regression coverage for monitored-client entity setup."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace

from custom_components.asus_wifi_diagnostics.models import (
    ClientPresenceState,
    MonitoredClient,
)


def _load_client_sensor(monkeypatch):
    """Load the HA-facing entity with only the narrow framework surface it uses."""
    sensor_module = ModuleType("homeassistant.components.sensor")
    sensor_module.SensorDeviceClass = SimpleNamespace(ENUM="enum")
    sensor_module.SensorEntity = type("SensorEntity", (), {})

    const_module = ModuleType("homeassistant.const")
    const_module.EntityCategory = SimpleNamespace(DIAGNOSTIC="diagnostic")

    coordinator_helper = ModuleType("homeassistant.helpers.update_coordinator")

    class CoordinatorEntity:
        """Provide the coordinator binding used by the real HA base class."""

        def __init__(self, coordinator) -> None:
            self.coordinator = coordinator

        @classmethod
        def __class_getitem__(cls, item):
            return cls

    coordinator_helper.CoordinatorEntity = CoordinatorEntity

    coordinator_module = ModuleType("custom_components.asus_wifi_diagnostics.coordinator")
    coordinator_module.AsusWifiDiagnosticsCoordinator = type(
        "AsusWifiDiagnosticsCoordinator", (), {}
    )

    monkeypatch.setitem(sys.modules, "homeassistant", ModuleType("homeassistant"))
    monkeypatch.setitem(sys.modules, "homeassistant.components", ModuleType("components"))
    monkeypatch.setitem(sys.modules, "homeassistant.components.sensor", sensor_module)
    monkeypatch.setitem(sys.modules, "homeassistant.const", const_module)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", ModuleType("helpers"))
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.update_coordinator", coordinator_helper)
    monkeypatch.setitem(
        sys.modules,
        "custom_components.asus_wifi_diagnostics.coordinator",
        coordinator_module,
    )
    sys.modules.pop("custom_components.asus_wifi_diagnostics.client_sensor", None)
    return importlib.import_module("custom_components.asus_wifi_diagnostics.client_sensor")


def test_entity_passes_its_configuration_generation_to_coordinator(monkeypatch) -> None:
    """An overlapping options reload cannot make entity setup look up a newer MAC map."""
    module = _load_client_sensor(monkeypatch)
    client = MonitoredClient(
        mac="D4:AD:FC:43:65:A2",
        name="Jacob Overhead 1",
        observer_profile="all_client_aps",
        band="2_4_ghz",
    )

    class Coordinator:
        def __init__(self) -> None:
            self.ownership = SimpleNamespace(by_device_id={})
            self.last_client_connected = {}
            self.received = None

        def presence_for(self, configured_client):
            self.received = configured_client
            return SimpleNamespace(state=ClientPresenceState.CONNECTED)

    coordinator = Coordinator()
    sensor = module.ClientPresenceSensor(coordinator, "entry-id", client)

    assert sensor.native_value == ClientPresenceState.CONNECTED.value
    assert coordinator.received is client
