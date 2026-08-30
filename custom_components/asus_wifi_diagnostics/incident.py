"""Pure incident detection and bounded evidence snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .models import NodeSnapshot, StationStats

HIGH_UTILIZATION_DURATION = timedelta(minutes=1)
UPTIME_RESET_TOLERANCE_SECONDS = 60


@dataclass(frozen=True, slots=True)
class WifiIncident:
    """A diagnostic event and its recorder-safe evidence."""

    event_type: str
    data: dict[str, Any]


def _station_score(station: StationStats) -> tuple[float, int, int]:
    """Sort retry pressure first, then weak signal and failures."""
    return (
        station.retry_percent or 0,
        -(station.rssi or -30),
        station.tx_failures or 0,
    )


def build_incident_snapshot(
    snapshot: NodeSnapshot, observed_at: datetime, started_at: datetime | None = None
) -> dict[str, Any]:
    """Build a bounded incident payload suitable for an EventEntity."""
    channel = snapshot.channel
    top_clients = sorted(snapshot.stations, key=_station_score, reverse=True)[:5]
    return {
        "observed_at": observed_at.isoformat(),
        "started_at": started_at.isoformat() if started_at else None,
        "node_name": snapshot.node.display_name,
        "node_mac": snapshot.node.mac,
        "node_ip": snapshot.node.host,
        "channel": channel.channel,
        "total_utilization": channel.busy,
        "transmit_airtime": channel.tx,
        "own_wifi_airtime": channel.in_bss,
        "other_wifi_airtime": channel.obss,
        "no_category_airtime": channel.no_category,
        "no_packet_airtime": channel.no_packet,
        "noise_floor": channel.noise,
        "channel_glitches": channel.glitches,
        "bad_plcp": channel.bad_plcp,
        "connected_clients": len(snapshot.stations),
        "router_uptime_seconds": snapshot.router_uptime_seconds,
        "top_clients": [
            {
                "name": station.name,
                "ip": station.ip,
                "mac": station.mac,
                "rssi": station.rssi,
                "tx_retry_percent": station.retry_percent,
                "tx_failures": station.tx_failures,
                "tx_rate_mbps": station.tx_rate_mbps,
                "rx_rate_mbps": station.rx_rate_mbps,
            }
            for station in top_clients
        ],
        "nearby_external_bssids": [
            {
                "ssid": network.ssid or "Hidden network",
                "bssid": network.bssid,
                "channel": network.channel,
                "rssi": network.rssi,
            }
            for network in snapshot.nearby_bss
            if not network.is_own_mesh
        ][:10],
    }


class IncidentTracker:
    """Turn consecutive snapshots into sparse diagnostic events."""

    def __init__(self, threshold: int, recovery_threshold: int = 70) -> None:
        self.threshold = threshold
        self.recovery_threshold = min(recovery_threshold, threshold - 1)
        self._was_reachable: bool | None = None
        self._previous_uptime: int | None = None
        self._high_started_at: datetime | None = None
        self._high_emitted = False

    def update(self, snapshot: NodeSnapshot | None, now: datetime) -> list[WifiIncident]:
        """Return zero or more events caused by the latest snapshot."""
        incidents: list[WifiIncident] = []
        if snapshot is None:
            if self._was_reachable is True:
                incidents.append(WifiIncident("node_unreachable", {"observed_at": now.isoformat()}))
            self._was_reachable = False
            self._previous_uptime = None
            self._high_started_at = None
            self._high_emitted = False
            return incidents

        if self._was_reachable is False:
            incidents.append(
                WifiIncident(
                    "node_recovered",
                    build_incident_snapshot(snapshot, now),
                )
            )
        self._was_reachable = True

        uptime = snapshot.router_uptime_seconds
        if (
            uptime is not None
            and self._previous_uptime is not None
            and uptime + UPTIME_RESET_TOLERANCE_SECONDS < self._previous_uptime
        ):
            incidents.append(
                WifiIncident(
                    "router_reboot",
                    build_incident_snapshot(snapshot, now),
                )
            )
        self._previous_uptime = uptime

        if snapshot.channel.busy >= self.threshold:
            if self._high_started_at is None:
                self._high_started_at = now
            elif (
                not self._high_emitted and now - self._high_started_at >= HIGH_UTILIZATION_DURATION
            ):
                incidents.append(
                    WifiIncident(
                        "high_utilization",
                        build_incident_snapshot(snapshot, now, self._high_started_at),
                    )
                )
                self._high_emitted = True
        elif snapshot.channel.busy < self.recovery_threshold:
            if self._high_emitted:
                data = build_incident_snapshot(snapshot, now, self._high_started_at)
                if self._high_started_at:
                    data["duration_seconds"] = int((now - self._high_started_at).total_seconds())
                incidents.append(WifiIncident("utilization_recovered", data))
            self._high_started_at = None
            self._high_emitted = False

        return incidents
