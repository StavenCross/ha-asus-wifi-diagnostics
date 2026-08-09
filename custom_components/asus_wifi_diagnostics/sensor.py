"""Sensor platform for ASUS Wi-Fi Diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import AsusWifiDiagnosticsConfigEntry
from .coordinator import AsusWifiDiagnosticsCoordinator
from .entity import AsusWifiDiagnosticsEntity
from .models import NodeSnapshot
from .probe import bssid_radio_fingerprint


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


def _worst_value(snapshot: NodeSnapshot, attribute: str) -> Any:
    station = snapshot.worst_station
    return getattr(station, attribute) if station else None


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
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:wifi",
        value_fn=lambda snapshot: snapshot.channel.busy,
    ),
    AsusWifiSensorDescription(
        key="overlapping_wifi",
        translation_key="overlapping_wifi",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:access-point-network",
        value_fn=lambda snapshot: snapshot.channel.obss,
        attrs_fn=_other_wifi_attrs,
    ),
    AsusWifiSensorDescription(
        key="noise_floor",
        translation_key="noise_floor",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda snapshot: snapshot.channel.noise,
    ),
    AsusWifiSensorDescription(
        key="connected_clients",
        translation_key="connected_clients",
        icon="mdi:devices",
        state_class=SensorStateClass.MEASUREMENT,
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
    AsusWifiSensorDescription(
        key="transmit_airtime",
        translation_key="transmit_airtime",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:upload-network",
        value_fn=lambda snapshot: snapshot.channel.tx,
    ),
    AsusWifiSensorDescription(
        key="own_wifi_airtime",
        translation_key="own_wifi_airtime",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:access-point-network",
        value_fn=lambda snapshot: snapshot.channel.in_bss,
    ),
    AsusWifiSensorDescription(
        key="no_category_airtime",
        translation_key="no_category_airtime",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:signal-off",
        value_fn=lambda snapshot: snapshot.channel.no_category,
    ),
    AsusWifiSensorDescription(
        key="no_packet_airtime",
        translation_key="no_packet_airtime",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:radio-tower",
        value_fn=lambda snapshot: snapshot.channel.no_packet,
    ),
    AsusWifiSensorDescription(
        key="channel_glitches",
        translation_key="channel_glitches",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:lightning-bolt",
        value_fn=lambda snapshot: snapshot.channel.glitches,
    ),
    AsusWifiSensorDescription(
        key="bad_plcp",
        translation_key="bad_plcp",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:alert-decagram-outline",
        value_fn=lambda snapshot: snapshot.channel.bad_plcp,
    ),
    AsusWifiSensorDescription(
        key="worst_client_retry",
        translation_key="worst_client_retry",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:backup-restore",
        value_fn=lambda snapshot: _worst_value(snapshot, "retry_percent"),
        attrs_fn=_worst_attrs,
    ),
    AsusWifiSensorDescription(
        key="worst_client_rssi",
        translation_key="worst_client_rssi",
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda snapshot: _worst_value(snapshot, "rssi"),
        attrs_fn=_worst_attrs,
    ),
    AsusWifiSensorDescription(
        key="worst_client_failures",
        translation_key="worst_client_failures",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:close-network-outline",
        value_fn=lambda snapshot: _worst_value(snapshot, "tx_failures"),
        attrs_fn=_worst_attrs,
    ),
    AsusWifiSensorDescription(
        key="router_uptime",
        translation_key="router_uptime",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:timer-outline",
        value_fn=lambda snapshot: snapshot.router_uptime_seconds,
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
    async_add_entities([CouchCastWifiProbeSensor(coordinator, entry.entry_id)])


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
            "diagnostic_key": self.entity_description.key,
            "node_name": self.node.display_name,
            "node_mac": self.node.mac,
            "channel": snapshot.channel.channel,
            "radio_interface": self.node.radio_interface,
            "node_ip": self.node.host,
        }
        if self.entity_description.attrs_fn:
            base.update(self.entity_description.attrs_fn(snapshot))
        return base


def _band_for(frequency_mhz: int) -> str:
    if 2400 <= frequency_mhz < 2500:
        return "2.4 GHz"
    if 4900 <= frequency_mhz < 5900:
        return "5 GHz"
    if 5925 <= frequency_mhz < 7125:
        return "6 GHz"
    return "Other"


class CouchCastWifiProbeSensor(CoordinatorEntity[AsusWifiDiagnosticsCoordinator], SensorEntity):
    """Represent the latest full-band survey from CouchCast."""

    _attr_icon = "mdi:access-point"
    _attr_name = "CouchCast external Wi-Fi networks"

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_couchcast_external_wifi"
        self._attr_device_info = DeviceInfo(
            identifiers={("asus_wifi_diagnostics", "couchcast_wifi_probe")},
            name="CouchCast Wi-Fi Probe",
            manufacturer="NetworkManager",
            model="Linux Wi-Fi survey probe",
        )

    @property
    def _report(self):
        return self.coordinator.data.probes.get("couchcast") if self.coordinator.data else None

    def _classified(self):
        report = self._report
        if report is None:
            return [], []
        own_bssids: set[str] = set()
        own_fingerprints: set[str] = set()
        own_ssids: set[str] = set()
        for snapshot in self.coordinator.data.nodes.values():
            own_fingerprints.add(bssid_radio_fingerprint(snapshot.node.mac))
            if snapshot.bssid:
                own_bssids.add(snapshot.bssid.upper())
            if snapshot.ssid:
                own_ssids.add(snapshot.ssid)
            own_bssids.update(network.bssid.upper() for network in snapshot.same_channel_mesh_bss)
            own_bssids.update(
                network.bssid.upper() for network in snapshot.nearby_bss if network.is_own_mesh
            )
        own, external = [], []
        for network in report.networks:
            is_own = (
                network.bssid in own_bssids
                or network.ssid in own_ssids
                or bssid_radio_fingerprint(network.bssid) in own_fingerprints
            )
            target = own if is_own else external
            target.append(network)
        return own, external

    @property
    def native_value(self) -> int | None:
        """Return the number of external BSSIDs currently visible."""
        if self._report is None:
            return None
        return len(self._classified()[1])

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return bounded, signal-sorted survey details."""
        report = self._report
        if report is None:
            return {
                "scan_available": False,
                "webhook_path": f"/api/webhook/{self.coordinator.webhook_id}",
            }
        own, external = self._classified()

        def attrs(network) -> dict[str, Any]:
            return {
                "ssid": network.ssid or "Hidden network",
                "bssid": network.bssid,
                "band": _band_for(network.frequency_mhz),
                "channel": network.channel,
                "frequency_mhz": network.frequency_mhz,
                "signal_percent": network.signal_percent,
                "security": network.security or "Open",
                "in_use": network.in_use,
            }

        channels: dict[tuple[str, int], dict[str, Any]] = {}
        for classification, networks in (("own", own), ("external", external)):
            for network in networks:
                key = (_band_for(network.frequency_mhz), network.channel)
                summary = channels.setdefault(
                    key,
                    {"band": key[0], "channel": key[1], "own": 0, "external": 0},
                )
                summary[classification] += 1
        connected = next((network for network in report.networks if network.in_use), None)
        return {
            "scan_available": True,
            "probe_name": report.name,
            "interface": report.interface,
            "collected_at": report.collected_at,
            "received_at": report.received_at,
            "connected_ssid": connected.ssid if connected else None,
            "connected_bssid": connected.bssid if connected else None,
            "own_mesh_bssids_seen": len(own),
            "external_bssids_seen": len(external),
            "external_2_4_ghz_seen": sum(
                1 for network in external if _band_for(network.frequency_mhz) == "2.4 GHz"
            ),
            "external_5_ghz_seen": sum(
                1 for network in external if _band_for(network.frequency_mhz) == "5 GHz"
            ),
            "channel_summary": sorted(
                channels.values(), key=lambda item: (item["band"], item["channel"])
            ),
            "own_mesh_bssids": [attrs(network) for network in own[:64]],
            "external_bssids": [attrs(network) for network in external[:96]],
            "webhook_path": f"/api/webhook/{self.coordinator.webhook_id}",
        }
