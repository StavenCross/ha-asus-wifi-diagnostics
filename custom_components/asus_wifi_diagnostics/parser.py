"""Pure parsers for ASUSWRT command output."""

from __future__ import annotations

import ipaddress
import re

from .const import RADIO_INTERFACES
from .models import ChannelStats, MeshNode, StationStats

_MAC_RE = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")
_NODE_RE = re.compile(
    r"<(?P<model>[^>]+)>(?P<host>[^>]+)>(?P<mac>(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})>(?P<role>[01])"
)


def normalize_model(model: str) -> str:
    """Normalize ASUS model names for interface selection."""
    return model.strip().upper().replace(" ", "_")


def radio_interface_for(model: str) -> str | None:
    """Return the known-safe 2.4 GHz interface for a model."""
    normalized = normalize_model(model)
    if normalized in RADIO_INTERFACES:
        return RADIO_INTERFACES[normalized]
    if "GT6" in normalized or "GT10" in normalized:
        return "eth6"
    if "XT8" in normalized or "AX95Q" in normalized:
        return "eth4"
    return None


def parse_mesh_nodes(raw: str) -> list[MeshNode]:
    """Parse ASUS cfg_device_list output."""
    nodes: list[MeshNode] = []
    for match in _NODE_RE.finditer(raw):
        host = str(ipaddress.ip_address(match.group("host")))
        model = match.group("model").strip()
        radio_interface = radio_interface_for(model)
        if radio_interface is None:
            continue
        is_controller = match.group("role") == "1"
        nodes.append(
            MeshNode(
                model=model,
                host=host,
                mac=match.group("mac").upper(),
                is_controller=is_controller,
                radio_interface=radio_interface,
                station_interface=radio_interface if is_controller else "wl0.1",
            )
        )
    return nodes


def parse_channel_stats(raw: str) -> ChannelStats:
    """Parse wl chanim_stats versions which may omit the busy column."""
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    header_index = next(i for i, line in enumerate(lines) if line.startswith("chanspec"))
    headers = lines[header_index].split()
    values = lines[header_index + 1].split()
    row = dict(zip(headers, values, strict=False))
    idle = int(row["idle"])
    return ChannelStats(
        channel=int(row["chanspec"], 0),
        tx=int(row["tx"]),
        in_bss=int(row["inbss"]),
        obss=int(row["obss"]),
        no_category=int(row["nocat"]),
        no_packet=int(row["nopkt"]),
        noise=int(row["knoise"]),
        idle=idle,
        busy=int(row.get("busy", 100 - idle)),
        glitches=int(row.get("glitch", 0)),
        bad_plcp=int(row.get("badplcp", 0)),
    )


def parse_assoclist(raw: str) -> list[str]:
    """Parse associated station MAC addresses."""
    return list(dict.fromkeys(mac.upper() for mac in _MAC_RE.findall(raw)))


def parse_leases(raw: str) -> dict[str, tuple[str, str | None]]:
    """Parse dnsmasq leases into MAC to IP/name."""
    leases: dict[str, tuple[str, str | None]] = {}
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) < 4 or not _MAC_RE.fullmatch(fields[1]):
            continue
        name = None if fields[3] == "*" else fields[3]
        leases[fields[1].upper()] = (fields[2], name)
    return leases


def _first_int(raw: str, patterns: tuple[str, ...]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, raw, re.IGNORECASE | re.MULTILINE)
        if match:
            return int(match.group(1))
    return None


def _first_rate(raw: str, label: str) -> float | None:
    match = re.search(rf"^\s*{re.escape(label)}\s*:?\s*([0-9.]+)", raw, re.I | re.M)
    return float(match.group(1)) if match else None


def parse_station_stats(
    mac: str, raw: str, lease: tuple[str, str | None] | None = None
) -> StationStats:
    """Parse wl sta_info output across ASUSWRT variants."""
    ip, name = lease or (None, None)
    return StationStats(
        mac=mac.upper(),
        ip=ip,
        name=name,
        rssi=_first_int(raw, (r"^\s*smoothed rssi\s*:?\s*(-?\d+)", r"^\s*rssi\s*:?\s*(-?\d+)")),
        noise=_first_int(raw, (r"^\s*noise\s*:?\s*(-?\d+)",)),
        tx_rate_mbps=_first_rate(raw, "rate of last tx pkt"),
        rx_rate_mbps=_first_rate(raw, "rate of last rx pkt"),
        tx_packets=_first_int(
            raw,
            (r"^\s*tx total pkts sent\s*:?\s*(\d+)", r"^\s*tx pkts\s*:?\s*(\d+)"),
        ),
        tx_retries=_first_int(
            raw,
            (r"^\s*tx pkts retries\s*:?\s*(\d+)", r"^\s*tx retries\s*:?\s*(\d+)"),
        ),
        tx_failures=_first_int(
            raw,
            (
                r"^\s*tx failures\s*:?\s*(\d+)",
                r"^\s*tx pkts retry exhausted\s*:?\s*(\d+)",
            ),
        ),
    )
