"""Tests for NetworkManager collector parsing."""

from collector.couchcast_wifi_probe import split_nmcli_terse


def test_split_nmcli_terse_preserves_bssid_colons() -> None:
    row = r"*:TheOneAndOnly:CA\:7C\:61\:1D\:81\:94:36:5180 MHz:78:WPA1 WPA2"
    assert split_nmcli_terse(row) == [
        "*",
        "TheOneAndOnly",
        "CA:7C:61:1D:81:94",
        "36",
        "5180 MHz",
        "78",
        "WPA1 WPA2",
    ]
