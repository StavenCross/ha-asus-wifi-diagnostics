"""Pure parsers for ASUSWRT command output."""

from __future__ import annotations

import ipaddress
import re

from .const import BAND_2_4_GHZ, BAND_5_GHZ, RADIO_5_GHZ_INTERFACES, RADIO_INTERFACES
from .models import ChannelStats, MeshNode, NearbyBss, StationStats

_MAC_RE = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")
_NODE_RE = re.compile(
    r"<(?P<model>[^>]+)>(?P<host>[^>]+)>(?P<mac>(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})>(?P<role>[01])"
)


def normalize_model(model: str) -> str:
    """Normalize ASUS model names for interface selection."""
    return model.strip().upper().replace(" ", "_")


def radio_interface_for(model: str, band: str = BAND_2_4_GHZ) -> str | None:
    """Return the known-safe client-facing interface for a model and band."""
    normalized = normalize_model(model)
    interfaces = RADIO_5_GHZ_INTERFACES if band == BAND_5_GHZ else RADIO_INTERFACES
    if normalized in interfaces:
        return interfaces[normalized]
    if band == BAND_5_GHZ:
        if "GT6" in normalized or "GT10" in normalized:
            return "eth4"
        if "XT8" in normalized or "AX95Q" in normalized:
            return "eth5"
        return None
    if "GT6" in normalized or "GT10" in normalized:
        return "eth6"
    if "XT8" in normalized or "AX95Q" in normalized:
        return "eth4"
    return None


def station_interface_for(
    model: str,
    is_controller: bool,
    radio_interface: str,
    band: str = BAND_2_4_GHZ,
) -> str:
    """Return the known-safe client BSS interface for a node model and band."""
    if is_controller:
        return radio_interface
    normalized = normalize_model(model)
    if band == BAND_5_GHZ:
        if "GT6" in normalized or "GT10" in normalized:
            return "wl0.1"
        return "wl1.1"
    if "GT6" in normalized or "GT10" in normalized:
        return "wl2.1"
    return "wl0.1"


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
                station_interface=station_interface_for(model, is_controller, radio_interface),
                observer_profile="main_mesh",
            )
        )
    return nodes


def expand_client_radios(node: MeshNode, model: str | None = None) -> list[MeshNode]:
    """Return supported 2.4 and client-facing 5 GHz radios for a physical node."""
    product = model or node.model
    radios: list[MeshNode] = []
    for band in (BAND_2_4_GHZ, BAND_5_GHZ):
        radio_interface = radio_interface_for(product, band)
        if radio_interface is None:
            continue
        radios.append(
            MeshNode(
                model=product,
                host=node.host,
                mac=node.mac,
                is_controller=node.is_controller,
                radio_interface=radio_interface,
                station_interface=station_interface_for(
                    product, node.is_controller, radio_interface, band
                ),
                band=band,
                observer_profile=node.observer_profile,
            )
        )
    return radios


def parse_standalone_identity(raw: str, host: str, observer_profile: str) -> MeshNode | None:
    """Build a safe standalone AP node from bounded ASUS identity output.

    Standalone APs are not present in the AiMesh controller inventory. The model must still map to
    an allowlisted radio interface before this function returns a pollable node.
    """
    model_raw, separator, mac_raw = raw.partition("__LAN_MAC__")
    model = model_raw.strip()
    mac_match = _MAC_RE.search(mac_raw if separator else "")
    radio_interface = radio_interface_for(model)
    if not model or mac_match is None or radio_interface is None:
        return None
    return MeshNode(
        model=model,
        host=str(ipaddress.ip_address(host)),
        mac=mac_match.group(0).upper(),
        is_controller=True,
        radio_interface=radio_interface,
        station_interface=station_interface_for(model, True, radio_interface),
        observer_profile=observer_profile,
    )


def parse_channel_stats(raw: str) -> ChannelStats:
    """Parse wl chanim_stats versions which may omit the busy column."""
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    header_index = next(i for i, line in enumerate(lines) if line.startswith("chanspec"))
    headers = lines[header_index].split()
    values = lines[header_index + 1].split()
    row = dict(zip(headers, values, strict=False))
    idle = int(row["idle"])
    raw_chanspec = row["chanspec"]
    width_suffixed = re.fullmatch(r"(?P<channel>\d+)/(?:20|40|80|160|320)", raw_chanspec)
    if width_suffixed:
        channel = int(width_suffixed.group("channel"))
    else:
        chanspec = int(raw_chanspec, 0)
        channel = chanspec & 0xFF if chanspec > 255 else chanspec
    return ChannelStats(
        channel=channel,
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


def parse_bssid(raw: str) -> str | None:
    """Return the first BSSID in wl output."""
    match = _MAC_RE.search(raw)
    return match.group(0).upper() if match else None


def parse_ssid(raw: str) -> str | None:
    """Return the SSID from wl output."""
    quoted = re.search(r'"(?P<ssid>.*)"', raw)
    if quoted:
        return quoted.group("ssid")
    _, separator, value = raw.partition(":")
    candidate = value.strip() if separator else raw.strip()
    return candidate or None


def parse_uptime_seconds(raw: str) -> int | None:
    """Return whole seconds from Linux /proc/uptime output."""
    first = raw.strip().split(maxsplit=1)
    if not first:
        return None
    try:
        value = float(first[0])
    except ValueError:
        return None
    return max(0, int(value))


def parse_scan_results(raw: str) -> list[NearbyBss]:
    """Parse bounded Broadcom wl scanresults output."""
    networks: list[NearbyBss] = []
    blocks = re.split(r"(?=^\s*SSID:\s*)", raw, flags=re.MULTILINE)
    for block in blocks:
        ssid_match = re.search(r'^\s*SSID:\s*"(?P<ssid>.*)"\s*$', block, re.MULTILINE)
        bssid_match = re.search(
            rf"^\s*BSSID:\s*(?P<bssid>{_MAC_RE.pattern})(?:\s|$)", block, re.MULTILINE
        )
        if not ssid_match or not bssid_match:
            continue
        channel_match = re.search(r"\bChannel:\s*(?P<channel>\d+)", block, re.I)
        if not channel_match:
            channel_match = re.search(r"\bchannel\s+(?P<channel>\d+)\b", block, re.I)
        rssi_match = re.search(r"\bRSSI:\s*(?P<rssi>-?\d+)", block, re.I)
        networks.append(
            NearbyBss(
                ssid=ssid_match.group("ssid"),
                bssid=bssid_match.group("bssid").upper(),
                channel=(int(channel_match.group("channel")) if channel_match else None),
                rssi=int(rssi_match.group("rssi")) if rssi_match else None,
            )
        )
    deduplicated = {network.bssid: network for network in networks}
    return sorted(
        deduplicated.values(),
        key=lambda network: network.rssi if network.rssi is not None else -999,
        reverse=True,
    )[:128]


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
    match = re.search(
        rf"^\s*{re.escape(label)}\s*:?\s*([0-9.]+)\s*(k?bps|mbps)?",
        raw,
        re.I | re.M,
    )
    if not match:
        return None
    rate = float(match.group(1))
    return rate / 1000 if (match.group(2) or "").lower() == "kbps" else rate


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
