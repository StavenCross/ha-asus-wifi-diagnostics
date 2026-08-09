"""Tests for ASUSWRT parsers."""

from custom_components.asus_wifi_diagnostics.parser import (
    parse_assoclist,
    parse_bssid,
    parse_channel_stats,
    parse_leases,
    parse_mesh_nodes,
    parse_scan_results,
    parse_ssid,
    parse_station_stats,
    parse_uptime_seconds,
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


def test_parse_gt6_satellite_uses_third_radio_bss() -> None:
    node = parse_mesh_nodes("<GT6>192.168.50.184>10:7C:61:1D:81:90>0")[0]
    assert node.station_interface == "wl2.1"


def test_parse_ax95q_satellite_uses_primary_radio_bss() -> None:
    node = parse_mesh_nodes("<RT-AX95Q>192.168.50.109>04:42:1A:38:B3:D0>0")[0]
    assert node.station_interface == "wl0.1"


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


def test_parse_encoded_24ghz_chanspec() -> None:
    raw = """version: 3
chanspec tx inbss obss nocat nopkt doze txop goodtx badtx glitch badplcp knoise idle timestamp
0x100b 5 2 30 4 7 0 52 0 0 100 2 -91 48 12345
"""
    assert parse_channel_stats(raw).channel == 11


def test_parse_clients_and_leases() -> None:
    assert parse_assoclist("assoclist AA:BB:CC:DD:EE:FF\nassoclist 11:22:33:44:55:66") == [
        "AA:BB:CC:DD:EE:FF",
        "11:22:33:44:55:66",
    ]
    leases = parse_leases("1770000000 aa:bb:cc:dd:ee:ff 192.168.50.20 kitchen-sensor 01:aa\n")
    assert leases["AA:BB:CC:DD:EE:FF"] == ("192.168.50.20", "kitchen-sensor")


def test_parse_bssid_and_ssid() -> None:
    assert parse_bssid("BSSID: aa:bb:cc:dd:ee:ff") == "AA:BB:CC:DD:EE:FF"
    assert parse_bssid("not associated") is None
    assert parse_ssid('Current SSID: "TheOneAndOnly"') == "TheOneAndOnly"


def test_parse_uptime_seconds() -> None:
    assert parse_uptime_seconds("12345.67 9000.00\n") == 12345
    assert parse_uptime_seconds("unavailable") is None


def test_parse_scan_results_is_signal_sorted_and_deduplicated() -> None:
    raw = """SSID: "Neighbor"
Mode: Managed RSSI: -71 dBm SNR: 20 dB noise: -91 dBm Channel: 1
BSSID: 11:22:33:44:55:66 Capability: ESS
Capability: ESS
SSID: "TheOneAndOnly"
Mode: Managed RSSI: -45 dBm SNR: 46 dB noise: -91 dBm Channel: 6
BSSID: AA:BB:CC:DD:EE:FF Capability: ESS WEP ShortSlot RRM
Capability: ESS
SSID: "Neighbor"
Mode: Managed RSSI: -70 dBm SNR: 21 dB noise: -91 dBm Channel: 1
BSSID: 11:22:33:44:55:66
Capability: ESS
"""
    networks = parse_scan_results(raw)
    assert [network.bssid for network in networks] == [
        "AA:BB:CC:DD:EE:FF",
        "11:22:33:44:55:66",
    ]
    assert networks[0].ssid == "TheOneAndOnly"
    assert networks[0].channel == 6
    assert networks[1].rssi == -70


def test_parse_station_stats() -> None:
    raw = """
        tx total pkts sent: 1000
        tx pkts retries: 125
        tx failures: 3
        smoothed rssi: -71
        noise: -92
        rate of last tx pkt: 24000 kbps
        rate of last rx pkt: 18.0 Mbps
    """
    stats = parse_station_stats("aa:bb:cc:dd:ee:ff", raw, ("192.168.50.20", "kitchen-sensor"))
    assert stats.rssi == -71
    assert stats.tx_retries == 125
    assert stats.tx_rate_mbps == 24.0
    assert stats.name == "kitchen-sensor"
