"""Tests for resilient ASUSWRT collection behavior."""

import asyncio
from importlib import import_module
from time import monotonic

import pytest

from custom_components.asus_wifi_diagnostics.api import (
    AsusWifiDiagnosticsApi,
    AuthenticationError,
    CannotConnectError,
    CommandError,
    HostKeyMismatchError,
    _failure_evidence,
)
from custom_components.asus_wifi_diagnostics.const import BAND_5_GHZ
from custom_components.asus_wifi_diagnostics.models import MeshNode, NodeFailureKind

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

    async def fake_run(host: str, command: str, expected_mac: str | None = None) -> str:
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
    assert result.generation == 1
    assert result.observed_at is not None


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

    async def fake_run(host: str, command: str, expected_mac: str | None = None) -> str:
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

    async def fake_run(host: str, command: str, expected_mac: str | None = None) -> str:
        if "dnsmasq.leases" in command:
            return ""
        raise CannotConnectError("offline")

    api._run = fake_run  # type: ignore[method-assign]
    result = asyncio.run(api.collect([NODE]))
    assert result.nodes == {}
    assert result.failures == {NODE.mac: "CannotConnectError"}
    assert result.failure_evidence[NODE.mac].kind is NodeFailureKind.UNREACHABLE
    assert result.failure_evidence[NODE.mac].outage_eligible is True


def test_discovers_allowlisted_standalone_access_point() -> None:
    """An explicit standalone XT8 contributes physical client radios with its profile."""
    api = AsusWifiDiagnosticsApi("192.168.50.1", "user", "password")

    async def fake_run(host: str, command: str, expected_mac: str | None = None) -> str:
        assert host == "192.168.50.168"
        assert "productid" in command
        return "XT8\n__LAN_MAC__\nC8:7F:54:A3:C8:80\n"

    api._run = fake_run  # type: ignore[method-assign]
    radios = asyncio.run(api.discover_standalone_access_point("192.168.50.168", "iot_ap"))

    assert [radio.band for radio in radios] == ["2_4_ghz", "5_ghz"]
    assert all(radio.observer_profile == "iot_ap" for radio in radios)
    assert all(radio.station_interface in {"eth4", "eth5"} for radio in radios)


def test_unavailable_standalone_ap_does_not_block_main_mesh_discovery() -> None:
    """Optional AP loss degrades its clients to unknown without unloading all diagnostics."""
    api = AsusWifiDiagnosticsApi(
        "192.168.50.1",
        "user",
        "password",
        additional_access_points={"192.168.50.168": "iot_ap"},
    )

    async def fake_run(host: str, command: str, expected_mac: str | None = None) -> str:
        if host == "192.168.50.168":
            raise CannotConnectError("offline")
        if "cfg_device_list" in command:
            return "<GT6>192.168.50.1>10:7C:61:1D:82:90>1"
        if "productid" in command:
            return "GT6\n"
        raise AssertionError(command)

    api._run = fake_run  # type: ignore[method-assign]
    radios = asyncio.run(api.discover_nodes())

    assert len(radios) == 2
    assert {radio.observer_profile for radio in radios} == {"main_mesh"}


def test_failure_evidence_separates_transport_loss_from_answering_ssh_faults() -> None:
    """Only a failed transport may become downstream LAN-outage evidence."""
    unreachable = _failure_evidence(CannotConnectError("offline"))
    trust = _failure_evidence(HostKeyMismatchError("changed"))
    authentication = _failure_evidence(AuthenticationError("denied"))
    command = _failure_evidence(CommandError("failed"))

    assert unreachable.transport_reachable is False
    assert unreachable.outage_eligible is True
    for evidence in (trust, authentication, command):
        assert evidence.transport_reachable is True
        assert evidence.outage_eligible is False


def test_mac_identity_pin_wins_over_stale_ip_pin_after_address_movement(monkeypatch) -> None:
    """A known physical node may safely retain trust when AiMesh assigns its prior IP elsewhere."""

    class FakeKey:
        """Return the fingerprint belonging to the expected physical node."""

        def get_fingerprint(self, algorithm: str) -> str:
            assert algorithm == "sha256"
            return "SHA256:office-node"

    class FakeConnection:
        """Provide the minimal asyncssh connection boundary used by verification."""

        def get_server_host_key(self):
            return FakeKey()

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    connection = FakeConnection()

    async def fake_connect(*args, **kwargs):
        return connection

    api_module = import_module("custom_components.asus_wifi_diagnostics.api")
    monkeypatch.setattr(api_module.asyncssh, "connect", fake_connect, raising=False)
    api = AsusWifiDiagnosticsApi(
        NODE.host,
        "user",
        "password",
        host_keys={
            NODE.host: "SHA256:living-node-at-old-address",
            f"mac:{NODE.mac}": "SHA256:office-node",
        },
    )

    result = asyncio.run(api._connect(NODE.host, NODE.mac))

    assert result is connection


def test_first_mac_pin_rejects_legacy_ip_that_now_answers_as_another_node(monkeypatch) -> None:
    """Initial v0.9 migration cannot bind an expected MAC from an IP fingerprint alone."""

    class FakeKey:
        """Return the fingerprint historically trusted for this IP address."""

        def get_fingerprint(self, algorithm: str) -> str:
            return "SHA256:legacy-ip-key"

    class FakeResult:
        """Report the different physical node now answering at the legacy address."""

        stdout = "E8:9C:25:8A:50:30\n"

    class FakeConnection:
        """Provide the identity command used before creating a new MAC pin."""

        def get_server_host_key(self):
            return FakeKey()

        async def run(self, command: str, check: bool):
            assert command == "nvram get lan_hwaddr"
            assert check is True
            return FakeResult()

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def fake_connect(*args, **kwargs):
        return FakeConnection()

    api_module = import_module("custom_components.asus_wifi_diagnostics.api")
    monkeypatch.setattr(api_module.asyncssh, "connect", fake_connect, raising=False)
    api = AsusWifiDiagnosticsApi(
        NODE.host,
        "user",
        "password",
        host_keys={NODE.host: "SHA256:legacy-ip-key"},
    )

    with pytest.raises(HostKeyMismatchError, match="answered as E8:9C:25:8A:50:30"):
        asyncio.run(api._connect(NODE.host, NODE.mac))

    assert f"mac:{NODE.mac}" not in api.host_keys
