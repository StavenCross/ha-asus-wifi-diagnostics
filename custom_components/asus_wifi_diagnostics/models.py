"""Data models for ASUS Wi-Fi Diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MeshNode:
    """An ASUS AiMesh node."""

    model: str
    host: str
    mac: str
    is_controller: bool = False
    radio_interface: str = ""
    station_interface: str = ""

    @property
    def display_name(self) -> str:
        """Return a stable fallback display name."""
        return f"{self.model} {self.host}"


@dataclass(frozen=True, slots=True)
class ChannelStats:
    """A 2.4 GHz chanim snapshot."""

    channel: int
    tx: int
    in_bss: int
    obss: int
    no_category: int
    no_packet: int
    noise: int
    idle: int
    busy: int
    glitches: int = 0
    bad_plcp: int = 0


@dataclass(frozen=True, slots=True)
class NearbyBss:
    """A BSS found in the router radio's cached scan results."""

    ssid: str
    bssid: str
    channel: int | None = None
    rssi: int | None = None
    is_own_mesh: bool = False


@dataclass(frozen=True, slots=True)
class StationStats:
    """A connected station snapshot."""

    mac: str
    ip: str | None = None
    name: str | None = None
    rssi: int | None = None
    noise: int | None = None
    tx_rate_mbps: float | None = None
    rx_rate_mbps: float | None = None
    tx_packets: int | None = None
    tx_retries: int | None = None
    tx_failures: int | None = None
    retry_percent_value: float | None = None

    @property
    def retry_percent(self) -> float | None:
        """Return retry percentage calculated from consecutive polls."""
        return self.retry_percent_value


@dataclass(frozen=True, slots=True)
class NodeSnapshot:
    """Metrics collected from one node."""

    node: MeshNode
    channel: ChannelStats
    bssid: str | None = None
    ssid: str | None = None
    nearby_bss: tuple[NearbyBss, ...] = field(default_factory=tuple)
    stations: tuple[StationStats, ...] = field(default_factory=tuple)

    @property
    def worst_station(self) -> StationStats | None:
        """Return the most suspicious station using retries then signal."""
        if not self.stations:
            return None

        def score(station: StationStats) -> tuple[float, int]:
            retry = station.retry_percent or 0
            weak_signal = -(station.rssi or -30)
            return retry, weak_signal

        return max(self.stations, key=score)


@dataclass(frozen=True, slots=True)
class NetworkSnapshot:
    """The latest network-wide snapshot."""

    nodes: dict[str, NodeSnapshot]
