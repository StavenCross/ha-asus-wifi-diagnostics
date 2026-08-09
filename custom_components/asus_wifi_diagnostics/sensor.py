"""Sensor platform for ASUS Wi-Fi Diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AsusWifiDiagnosticsConfigEntry
from .entity import AsusWifiDiagnosticsEntity
from .models import NodeSnapshot


@dataclass(frozen=True, kw_only=True)
class AsusWifiSensorDescription(SensorEntityDescription):
    """Describe an ASUS Wi-Fi sensor."""

    value_fn: Callable[[NodeSnapshot], Any]
    attrs_fn: Callable[[NodeSnapshot], dict[str, Any]] | None = None


def _diagnosis(snapshot: NodeSnapshot) -> str:
    channel = snapshot.channel
    worst = snapshot.worst_station
    if channel.busy < 70:
        return "normal"
    if channel.obss >= 20:
        return "other_wifi_contention"
    if channel.no_category + channel.no_packet >= 15:
        return "non_wifi_interference"
    if worst and ((worst.retry_percent or 0) >= 25 or (worst.rssi or 0) <= -75):
        return "client_pressure"
    return "general_congestion"


def _worst_attrs(snapshot: NodeSnapshot) -> dict[str, Any]:
    station = snapshot.worst_station
    if station is None:
        return {}
    return {
        "mac": station.mac,
        "ip": station.ip,
        "name": station.name,
        "rssi": station.rssi,
        "noise": station.noise,
        "tx_rate_mbps": station.tx_rate_mbps,
        "rx_rate_mbps": station.rx_rate_mbps,
        "tx_retry_percent": station.retry_percent,
        "tx_failures": station.tx_failures,
    }


def _client_map_attrs(snapshot: NodeSnapshot) -> dict[str, Any]:
    """Return a bounded, IP-sorted client map for dashboard rendering."""

    def ip_key(station) -> tuple[int, int, int, int]:
        if not station.ip:
            return (999, 999, 999, 999)
        try:
            parts = tuple(int(part) for part in station.ip.split("."))
        except ValueError:
            return (999, 999, 999, 999)
        return parts if len(parts) == 4 else (999, 999, 999, 999)

    return {
        "clients": [
            {
                "name": station.name,
                "ip": station.ip,
                "mac": station.mac,
                "rssi": station.rssi,
                "tx_rate_mbps": station.tx_rate_mbps,
                "rx_rate_mbps": station.rx_rate_mbps,
                "tx_retry_percent": station.retry_percent,
                "tx_failures": station.tx_failures,
            }
            for station in sorted(snapshot.stations, key=ip_key)
        ]
    }


def _other_wifi_attrs(snapshot: NodeSnapshot) -> dict[str, Any]:
    """Explain which cached nearby BSSIDs are own mesh versus external."""

    def network_attrs(network) -> dict[str, Any]:
        return {
            "ssid": network.ssid or "Hidden network",
            "bssid": network.bssid,
            "channel": network.channel,
            "rssi": network.rssi,
        }

    own_mesh = [network for network in snapshot.nearby_bss if network.is_own_mesh]
    external = [network for network in snapshot.nearby_bss if not network.is_own_mesh]
    return {
        "local_bssid": snapshot.bssid,
        "local_ssid": snapshot.ssid,
        "scan_source": "current_channel_passive_scan",
        "scan_available": bool(snapshot.nearby_bss),
        "same_channel_mesh_radios": len(snapshot.same_channel_mesh_bss),
        "same_channel_mesh_bssids": [
            network_attrs(network) for network in snapshot.same_channel_mesh_bss
        ],
        "own_mesh_bssids_seen": len(own_mesh),
        "external_bssids_seen": len(external),
        "own_mesh_bssids": [network_attrs(network) for network in own_mesh[:32]],
        "external_bssids": [network_attrs(network) for network in external[:64]],
    }


SENSORS = (
    AsusWifiSensorDescription(
        key="utilization",
        translation_key="utilization",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:wifi",
        value_fn=lambda snapshot: snapshot.channel.busy,
    ),
    AsusWifiSensorDescription(
        key="overlapping_wifi",
        translation_key="overlapping_wifi",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:access-point-network",
        value_fn=lambda snapshot: snapshot.channel.obss,
        attrs_fn=_other_wifi_attrs,
    ),
    AsusWifiSensorDescription(
        key="noise_floor",
        translation_key="noise_floor",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class="signal_strength",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda snapshot: snapshot.channel.noise,
    ),
    AsusWifiSensorDescription(
        key="connected_clients",
        translation_key="connected_clients",
        icon="mdi:devices",
        value_fn=lambda snapshot: len(snapshot.stations),
        attrs_fn=_client_map_attrs,
    ),
    AsusWifiSensorDescription(
        key="diagnosis",
        translation_key="diagnosis",
        icon="mdi:stethoscope",
        value_fn=_diagnosis,
    ),
    AsusWifiSensorDescription(
        key="worst_client",
        translation_key="worst_client",
        icon="mdi:wifi-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda snapshot: (
            (snapshot.worst_station.name or snapshot.worst_station.mac)
            if snapshot.worst_station
            else None
        ),
        attrs_fn=_worst_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AsusWifiDiagnosticsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up diagnostic sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        AsusWifiSensor(coordinator, node, description)
        for node in coordinator.nodes
        for description in SENSORS
    )


class AsusWifiSensor(AsusWifiDiagnosticsEntity, SensorEntity):
    """A radio or client diagnostic sensor."""

    entity_description: AsusWifiSensorDescription

    def __init__(self, coordinator, node, description: AsusWifiSensorDescription) -> None:
        self.entity_description = description
        super().__init__(coordinator, node)

    @property
    def native_value(self):
        """Return the current sensor value."""
        snapshot = self.coordinator.snapshot_for(self.node.mac)
        return self.entity_description.value_fn(snapshot) if snapshot else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return bounded supporting details."""
        snapshot = self.coordinator.snapshot_for(self.node.mac)
        if snapshot is None:
            return None
        base = {
            "channel": snapshot.channel.channel,
            "radio_interface": self.node.radio_interface,
            "node_ip": self.node.host,
        }
        if self.entity_description.attrs_fn:
            base.update(self.entity_description.attrs_fn(snapshot))
        return base
