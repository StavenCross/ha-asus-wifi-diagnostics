"""Tests for resilient ASUSWRT collection behavior."""

import asyncio
from time import monotonic

from custom_components.asus_wifi_diagnostics.api import (
    AsusWifiDiagnosticsApi,
    CannotConnectError,
)
from custom_components.asus_wifi_diagnostics.const import BAND_5_GHZ
from custom_components.asus_wifi_diagnostics.models import MeshNode

NODE = MeshNode(
    model="GT6",
    host="192.168.50.1",
    mac="10:7C:61:1D:82:90",
    is_controller=True,
    radio_interface="eth6",
    station_interface="eth6",
)

CHANIM = """version: 4
chanspec tx inbss obss nocat nopkt doze txop goodtx badtx glitch badplcp knoise idle busy timestamp
11 10 3 29 5 9 0 42 1 1 2279 41 -92 51 54 668304384
"""


def test_collects_router_uptime() -> None:
    api = AsusWifiDiagnosticsApi("192.168.50.1", "user", "password")
    api._last_passive_scan[NODE.snapshot_key] = monotonic()

    async def fake_run(host: str, command: str) -> str:
        if "dnsmasq.leases" in command:
            return ""
        return (
            f"{CHANIM}\n__BSSID__\nBSSID: AA:BB:CC:DD:EE:FF"
            '\n__SSID__\nCurrent SSID: "TheOneAndOnly"'
            "\n__SCAN__\n\n__UPTIME__\n12345.67 10000.00"
            "\n__ASSOC__\n"
        )

    api._run = fake_run  # type: ignore[method-assign]
    result = asyncio.run(api.collect([NODE]))
    assert result.nodes[NODE.mac].router_uptime_seconds == 12345
    assert result.failures == {}


def test_collect_keeps_24_and_5_ghz_snapshots_separate() -> None:
    api = AsusWifiDiagnosticsApi("192.168.50.1", "user", "password")
    five_ghz = MeshNode(
        model="GT10",
        host=NODE.host,
        mac=NODE.mac,
        is_controller=True,
        radio_interface="eth4",
        station_interface="eth4",
        band=BAND_5_GHZ,
    )
    api._last_passive_scan[NODE.snapshot_key] = monotonic()
    api._last_passive_scan[five_ghz.snapshot_key] = monotonic()

    async def fake_run(host: str, command: str) -> str:
        if "dnsmasq.leases" in command:
            return ""
        channel = 149 if "eth4" in command else 11
        chanim = CHANIM.replace("\n11 10", f"\n{channel} 10")
        return (
            f"{chanim}\n__BSSID__\nBSSID: AA:BB:CC:DD:EE:FF"
            '\n__SSID__\nCurrent SSID: "TheOneAndOnly"'
            "\n__SCAN__\n\n__UPTIME__\n12345.67 10000.00"
            "\n__ASSOC__\n"
        )

    api._run = fake_run  # type: ignore[method-assign]
    result = asyncio.run(api.collect([NODE, five_ghz]))
    assert result.nodes[NODE.snapshot_key].channel.channel == 11
    assert result.nodes[five_ghz.snapshot_key].channel.channel == 149


def test_collect_returns_node_failure_instead_of_stale_success() -> None:
    api = AsusWifiDiagnosticsApi("192.168.50.1", "user", "password")

    async def fake_run(host: str, command: str) -> str:
        if "dnsmasq.leases" in command:
            return ""
        raise CannotConnectError("offline")

    api._run = fake_run  # type: ignore[method-assign]
    result = asyncio.run(api.collect([NODE]))
    assert result.nodes == {}
    assert result.failures == {NODE.mac: "CannotConnectError"}
