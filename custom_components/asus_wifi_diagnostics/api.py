"""Read-only SSH client for ASUSWRT diagnostics."""

from __future__ import annotations

import asyncio
import logging
import shlex
from collections.abc import Callable
from dataclasses import replace
from time import monotonic

import asyncssh

from .models import MeshNode, NearbyBss, NetworkSnapshot, NodeSnapshot
from .parser import (
    parse_assoclist,
    parse_bssid,
    parse_channel_stats,
    parse_leases,
    parse_mesh_nodes,
    parse_scan_results,
    parse_ssid,
    parse_station_stats,
    radio_interface_for,
    station_interface_for,
)

_LOGGER = logging.getLogger(__name__)
_PASSIVE_SCAN_INTERVAL_SECONDS = 15 * 60


class AsusWifiDiagnosticsError(Exception):
    """Base integration error."""


class AuthenticationError(AsusWifiDiagnosticsError):
    """Authentication failed."""


class CannotConnectError(AsusWifiDiagnosticsError):
    """Connection failed."""


class UnsupportedRouterError(AsusWifiDiagnosticsError):
    """No known-safe radio interface was found."""


class AsusWifiDiagnosticsApi:
    """Collect ASUS Wi-Fi data using bounded, read-only commands."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        host_keys: dict[str, str] | None = None,
        host_key_callback: Callable[[str, str], None] | None = None,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.host_keys = host_keys or {}
        self.host_key_callback = host_key_callback
        self._station_counters: dict[tuple[str, str], tuple[int, int, int | None]] = {}
        self._last_passive_scan: dict[str, float] = {}

    async def _connect(self, host: str) -> asyncssh.SSHClientConnection:
        try:
            connection = await asyncssh.connect(
                host,
                username=self.username,
                password=self.password,
                known_hosts=None,
                connect_timeout=8,
                login_timeout=8,
            )
        except asyncssh.PermissionDenied as err:
            raise AuthenticationError from err
        except (TimeoutError, asyncssh.Error, OSError) as err:
            raise CannotConnectError(str(err)) from err

        fingerprint = connection.get_server_host_key().get_fingerprint("sha256")
        expected = self.host_keys.get(host)
        if expected is not None and expected != fingerprint:
            connection.close()
            await connection.wait_closed()
            raise CannotConnectError(f"Host key changed for {host}")
        if expected is None:
            self.host_keys[host] = fingerprint
            if self.host_key_callback:
                self.host_key_callback(host, fingerprint)
        return connection

    async def _run(self, host: str, command: str) -> str:
        connection = await self._connect(host)
        try:
            result = await asyncio.wait_for(connection.run(command, check=True), 15)
            return result.stdout
        except (TimeoutError, asyncssh.Error) as err:
            raise CannotConnectError(f"Command failed on {host}: {err}") from err
        finally:
            connection.close()
            await connection.wait_closed()

    async def discover_nodes(self) -> list[MeshNode]:
        """Discover supported AiMesh nodes from the controller."""
        raw = await self._run(self.host, "nvram get cfg_device_list")
        nodes = parse_mesh_nodes(raw)
        if not nodes:
            raise UnsupportedRouterError("No supported AiMesh nodes found")

        async def identify(node: MeshNode) -> MeshNode:
            try:
                product = (await self._run(node.host, "nvram get productid")).strip()
            except AsusWifiDiagnosticsError:
                return node
            radio_interface = radio_interface_for(product) or node.radio_interface
            return replace(
                node,
                radio_interface=radio_interface,
                station_interface=station_interface_for(
                    product, node.is_controller, radio_interface
                ),
            )

        return list(await asyncio.gather(*(identify(node) for node in nodes)))

    async def _collect_node(
        self, node: MeshNode, leases: dict[str, tuple[str, str | None]]
    ) -> NodeSnapshot:
        radio = shlex.quote(node.radio_interface)
        station = shlex.quote(node.station_interface)
        command = (
            f"wl -i {radio} chanim_stats; printf '\\n__BSSID__\\n'; "
            f"wl -i {station} cur_etheraddr 2>/dev/null || true; "
            f"printf '\\n__SSID__\\n'; wl -i {station} ssid 2>/dev/null || true; "
            f"printf '\\n__SCAN__\\n'; "
            f"wl -i {radio} scanresults 2>/dev/null | head -n 1024; "
            f"printf '\\n__ASSOC__\\n'; "
            f"wl -i {station} assoclist"
        )
        output = await self._run(node.host, command)
        channel_raw, remainder = output.split("__BSSID__", 1)
        bssid_raw, remainder = remainder.split("__SSID__", 1)
        ssid_raw, remainder = remainder.split("__SCAN__", 1)
        scan_raw, assoc_raw = remainder.split("__ASSOC__", 1)
        station_macs = parse_assoclist(assoc_raw)[:128]

        stations = []
        if station_macs:
            macs = " ".join(shlex.quote(mac) for mac in station_macs)
            station_output = await self._run(
                node.host,
                f"for mac in {macs}; do printf '\\n__STA__ %s\\n' \"$mac\"; "
                f'wl -i {station} sta_info "$mac"; done',
            )
            parts = station_output.split("__STA__ ")[1:]
            for part in parts:
                first_line, _, body = part.partition("\n")
                mac = first_line.strip().upper()
                stations.append(parse_station_stats(mac, body, leases.get(mac)))

        channel = parse_channel_stats(channel_raw)
        nearby_bss = tuple(parse_scan_results(scan_raw))
        last_scan = self._last_passive_scan.get(node.host, 0)
        if monotonic() - last_scan >= _PASSIVE_SCAN_INTERVAL_SECONDS:
            try:
                fresh_scan_raw = await self._run(
                    node.host,
                    f"wl -i {radio} scan -t passive -c {channel.channel} "
                    f">/dev/null 2>&1 && sleep 1 && "
                    f"wl -i {radio} scanresults 2>/dev/null | head -n 1024",
                )
                nearby_bss = tuple(parse_scan_results(fresh_scan_raw))
                self._last_passive_scan[node.host] = monotonic()
            except AsusWifiDiagnosticsError as err:
                _LOGGER.debug("Passive scan unavailable on %s: %s", node.host, err)

        return NodeSnapshot(
            node=node,
            channel=channel,
            bssid=parse_bssid(bssid_raw),
            ssid=parse_ssid(ssid_raw),
            nearby_bss=nearby_bss,
            stations=tuple(stations),
        )

    async def collect(self, nodes: list[MeshNode]) -> NetworkSnapshot:
        """Collect a network snapshot, preserving reachable nodes."""
        leases_raw = await self._run(
            self.host, "cat /var/lib/misc/dnsmasq.leases 2>/dev/null || true"
        )
        leases = parse_leases(leases_raw)
        results = await asyncio.gather(
            *(self._collect_node(node, leases) for node in nodes),
            return_exceptions=True,
        )
        own_bssids = {
            result.bssid
            for result in results
            if isinstance(result, NodeSnapshot) and result.bssid is not None
        }
        reachable = [result for result in results if isinstance(result, NodeSnapshot)]
        snapshots: dict[str, NodeSnapshot] = {}
        for node, result in zip(nodes, results, strict=True):
            if isinstance(result, Exception):
                _LOGGER.warning(
                    "Could not collect Wi-Fi diagnostics from %s: %s", node.host, result
                )
                continue
            stations = []
            for station in result.stations:
                key = (node.mac, station.mac)
                previous = self._station_counters.get(key)
                retry_percent = None
                failure_delta = None
                if station.tx_packets is not None and station.tx_retries is not None:
                    self._station_counters[key] = (
                        station.tx_packets,
                        station.tx_retries,
                        station.tx_failures,
                    )
                    if previous:
                        packet_delta = station.tx_packets - previous[0]
                        retry_delta = station.tx_retries - previous[1]
                        if packet_delta > 0 and retry_delta >= 0:
                            attempts = packet_delta + retry_delta
                            retry_percent = round(100 * retry_delta / attempts, 1)
                        if station.tx_failures is not None and previous[2] is not None:
                            raw_failure_delta = station.tx_failures - previous[2]
                            if raw_failure_delta >= 0:
                                failure_delta = raw_failure_delta
                stations.append(
                    replace(
                        station,
                        retry_percent_value=retry_percent,
                        tx_failures=failure_delta,
                    )
                )
            nearby_bss = tuple(
                replace(network, is_own_mesh=network.bssid in own_bssids)
                for network in result.nearby_bss
            )
            same_channel_mesh_bss = tuple(
                NearbyBss(
                    ssid=other.ssid or "Unknown mesh SSID",
                    bssid=other.bssid,
                    channel=other.channel.channel,
                    is_own_mesh=True,
                )
                for other in reachable
                if other.bssid is not None
                and other.bssid != result.bssid
                and other.channel.channel == result.channel.channel
            )
            snapshots[node.mac] = replace(
                result,
                nearby_bss=nearby_bss,
                same_channel_mesh_bss=same_channel_mesh_bss,
                stations=tuple(stations),
            )
        if not snapshots:
            raise CannotConnectError("No AiMesh node returned diagnostics")
        return NetworkSnapshot(nodes=snapshots)
