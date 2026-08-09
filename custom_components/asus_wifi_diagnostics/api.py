"""Read-only SSH client for ASUSWRT diagnostics."""

from __future__ import annotations

import asyncio
import logging
import shlex
from collections.abc import Callable
from dataclasses import replace

import asyncssh

from .models import MeshNode, NetworkSnapshot, NodeSnapshot
from .parser import (
    parse_assoclist,
    parse_channel_stats,
    parse_leases,
    parse_mesh_nodes,
    parse_station_stats,
    radio_interface_for,
    station_interface_for,
)

_LOGGER = logging.getLogger(__name__)


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
        self._station_counters: dict[tuple[str, str], tuple[int, int]] = {}

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
            f"wl -i {radio} chanim_stats; printf '\\n__ASSOC__\\n'; "
            f"wl -i {station} assoclist"
        )
        output = await self._run(node.host, command)
        channel_raw, assoc_raw = output.split("__ASSOC__", 1)
        station_macs = parse_assoclist(assoc_raw)[:128]

        stations = []
        if station_macs:
            macs = " ".join(shlex.quote(mac) for mac in station_macs)
            station_output = await self._run(
                node.host,
                f"for mac in {macs}; do printf '\\n__STA__ %s\\n' \"$mac\"; "
                f"wl -i {station} sta_info \"$mac\"; done",
            )
            parts = station_output.split("__STA__ ")[1:]
            for part in parts:
                first_line, _, body = part.partition("\n")
                mac = first_line.strip().upper()
                stations.append(parse_station_stats(mac, body, leases.get(mac)))

        return NodeSnapshot(
            node=node,
            channel=parse_channel_stats(channel_raw),
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
                if station.tx_packets is not None and station.tx_retries is not None:
                    self._station_counters[key] = (station.tx_packets, station.tx_retries)
                    if previous:
                        packet_delta = station.tx_packets - previous[0]
                        retry_delta = station.tx_retries - previous[1]
                        if packet_delta > 0 and retry_delta >= 0:
                            retry_percent = round(100 * retry_delta / packet_delta, 1)
                stations.append(replace(station, retry_percent_value=retry_percent))
            snapshots[node.mac] = replace(result, stations=tuple(stations))
        if not snapshots:
            raise CannotConnectError("No AiMesh node returned diagnostics")
        return NetworkSnapshot(nodes=snapshots)
