"""Data models for ASUS Wi-Fi Diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from .const import BAND_2_4_GHZ, BAND_5_GHZ


@dataclass(frozen=True, slots=True)
class MeshNode:
    """An ASUS AiMesh node."""

    model: str
    host: str
    mac: str
    is_controller: bool = False
    radio_interface: str = ""
    station_interface: str = ""
    band: str = BAND_2_4_GHZ
    observer_profile: str = "main_mesh"

    @property
    def display_name(self) -> str:
        """Return a stable fallback display name."""
        return f"{self.model} {self.host}"

    @property
    def band_name(self) -> str:
        """Return the user-facing radio band name."""
        return "5 GHz" if self.band == BAND_5_GHZ else "2.4 GHz"

    @property
    def band_slug(self) -> str:
        """Return the stable unique-ID segment for this radio band."""
        return "5ghz" if self.band == BAND_5_GHZ else "2ghz"

    @property
    def snapshot_key(self) -> str:
        """Return a unique snapshot key while preserving legacy 2.4 GHz keys."""
        return f"{self.mac}_5ghz" if self.band == BAND_5_GHZ else self.mac


@dataclass(frozen=True, slots=True)
class ChannelStats:
    """A Wi-Fi radio chanim snapshot."""

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
class ProbeBss:
    """A BSS observed by an external Wi-Fi probe."""

    ssid: str
    bssid: str
    channel: int
    frequency_mhz: int
    signal_percent: int
    security: str
    in_use: bool = False


@dataclass(frozen=True, slots=True)
class ProbeSnapshot:
    """A bounded nearby-network survey reported by a probe."""

    probe_id: str
    name: str
    interface: str
    collected_at: str
    received_at: str
    networks: tuple[ProbeBss, ...] = field(default_factory=tuple)


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
    same_channel_mesh_bss: tuple[NearbyBss, ...] = field(default_factory=tuple)
    stations: tuple[StationStats, ...] = field(default_factory=tuple)
    router_uptime_seconds: int | None = None

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
    """The latest network-wide snapshot and its completeness generation.

    Nodes contains only successful radio observations. Failures preserves every expected radio
    which did not produce a current result so downstream client presence never mistakes an SSH or
    collection failure for device absence.
    """

    nodes: dict[str, NodeSnapshot]
    probes: dict[str, ProbeSnapshot] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    failure_evidence: dict[str, NodeFailureEvidence] = field(default_factory=dict)
    generation: int = 0
    observed_at: datetime | None = None


class NodeFailureKind(StrEnum):
    """Classify why one expected router radio did not return current metrics.

    Reachability is intentionally separate from diagnostic success. An SSH host-key, login, or
    command failure proves that a network endpoint answered even though this integration could not
    safely collect from it; only a transport failure is eligible evidence of a LAN outage.
    """

    UNREACHABLE = "unreachable"
    HOST_KEY_MISMATCH = "host_key_mismatch"
    AUTHENTICATION = "authentication"
    COMMAND = "command"
    COLLECTION = "collection"


@dataclass(frozen=True, slots=True)
class NodeFailureEvidence:
    """Describe one bounded node failure for automation-safe downstream use.

    ``transport_reachable`` is true only when the failed attempt still proved an answering SSH
    endpoint. ``outage_eligible`` is deliberately narrower: House Lighting may count only true
    transport loss toward a coherent network-outage quorum.
    """

    kind: NodeFailureKind
    source_error: str
    transport_reachable: bool | None
    outage_eligible: bool


class ClientPresenceState(StrEnum):
    """Describe the only router-side outcomes exposed for a monitored client."""

    CONNECTED = "connected"
    NOT_CONNECTED = "not_connected"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class MonitoredClient:
    """Describe one operator-enrolled MAC and the observers allowed to judge it.

    The optional Home Assistant device preserves the existing ownership link, while name and
    observer profile allow infrastructure clients to be monitored without inventing a HA device.
    """

    mac: str
    name: str
    observer_profile: str
    band: str
    ha_device_id: str | None = None


@dataclass(frozen=True, slots=True)
class ClientPresenceObservation:
    """Return one complete, attributable router-side client-presence decision."""

    client: MonitoredClient
    state: ClientPresenceState
    generation: int
    observed_at: datetime | None
    eligible_observers: tuple[str, ...]
    queried_observers: tuple[str, ...]
    failed_observers: tuple[str, ...]
    association: tuple[MeshNode, StationStats] | None = None
