"""Tests for ASUSWRT parsers."""

from custom_components.asus_wifi_diagnostics.parser import (
    parse_assoclist,
    parse_channel_stats,
    parse_leases,
    parse_mesh_nodes,
    parse_station_stats,
)


def test_parse_mesh_nodes_uses_safe_model_interfaces() -> None:
    raw = (
        "<GT6>192.168.50.1>10:7C:61:1D:82:90>1"
        "<ZenWiFi_XT8>192.168.50.168>C8:7F:54:A3:C8:80>0"
        "<Unknown>192.168.50.200>AA:BB:CC:DD:EE:FF>0"
    )
    nodes = parse_mesh_nodes(raw)
    assert len(nodes) == 2
    assert nodes[0].radio_interface == "eth6"
    assert nodes[0].station_interface == "eth6"
    assert nodes[1].radio_interface == "eth4"
    assert nodes[1].station_interface == "wl0.1"


def test_parse_chanim_v4() -> None:
    raw = """version: 4
chanspec tx inbss obss nocat nopkt doze txop goodtx badtx glitch badplcp knoise idle busy timestamp
11 10 3 29 5 9 0 42 1 1 2279 41 -92 51 54 668304384
"""
    stats = parse_channel_stats(raw)
    assert stats.channel == 11
    assert stats.busy == 54
    assert stats.obss == 29
    assert stats.noise == -92


def test_parse_chanim_v3_derives_busy() -> None:
    raw = """version: 3
chanspec tx inbss obss nocat nopkt doze txop goodtx badtx glitch badplcp knoise idle timestamp
11 5 2 30 4 7 0 52 0 0 100 2 -91 48 12345
"""
    assert parse_channel_stats(raw).busy == 52


def test_parse_clients_and_leases() -> None:
    assert parse_assoclist("assoclist AA:BB:CC:DD:EE:FF\nassoclist 11:22:33:44:55:66") == [
        "AA:BB:CC:DD:EE:FF",
        "11:22:33:44:55:66",
    ]
    leases = parse_leases(
        "1770000000 aa:bb:cc:dd:ee:ff 192.168.50.20 kitchen-sensor 01:aa\n"
    )
    assert leases["AA:BB:CC:DD:EE:FF"] == ("192.168.50.20", "kitchen-sensor")


def test_parse_station_stats() -> None:
    raw = """
        tx total pkts sent: 1000
        tx pkts retries: 125
        tx failures: 3
        smoothed rssi: -71
        noise: -92
        rate of last tx pkt: 24.0 Mbps
        rate of last rx pkt: 18.0 Mbps
    """
    stats = parse_station_stats(
        "aa:bb:cc:dd:ee:ff", raw, ("192.168.50.20", "kitchen-sensor")
    )
    assert stats.rssi == -71
    assert stats.tx_retries == 125
    assert stats.tx_rate_mbps == 24.0
    assert stats.name == "kitchen-sensor"
