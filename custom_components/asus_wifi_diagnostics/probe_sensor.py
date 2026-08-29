"""CouchCast full-band Wi-Fi survey entity.

The collector observes nearby BSSIDs for congestion context; it does not report client association
and therefore remains separate from the monitored-client presence contract.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import AsusWifiDiagnosticsCoordinator
from .probe import bssid_radio_fingerprint


def _band_for(frequency_mhz: int) -> str:
    """Return a compact user-facing Wi-Fi band for a survey frequency."""
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
        """Bind the external survey to its stable integration-owned device."""
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
        """Return the current CouchCast report, if one has arrived."""
        return self.coordinator.data.probes.get("couchcast") if self.coordinator.data else None

    def _classified(self):
        """Partition observed BSSIDs into this household's radios and external networks."""
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
            (own if is_own else external).append(network)
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
