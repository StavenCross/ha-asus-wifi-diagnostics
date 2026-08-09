"""Tests for conservative Home Assistant device ownership matching."""

from custom_components.asus_wifi_diagnostics.ownership import (
    OwnershipIndex,
    OwnershipRecord,
    normalize_ip,
    normalize_mac,
)

CAMERA = OwnershipRecord(
    device_id="camera-device",
    name="Office camera",
    area_id="office",
    area_name="Office",
    integrations=("nest",),
)
PRINTER = OwnershipRecord(
    device_id="printer-device",
    name="Office printer",
    integrations=("ipp",),
)


def test_normalize_network_identities() -> None:
    assert normalize_mac("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"
    assert normalize_mac("not-a-mac") is None
    assert normalize_ip("192.168.50.41") == "192.168.50.41"
    assert normalize_ip("printer.local") is None


def test_exact_mac_match_includes_ha_navigation_metadata() -> None:
    index = OwnershipIndex(
        by_mac={"AA:BB:CC:DD:EE:FF": CAMERA},
        by_ip={},
        by_device_id={CAMERA.device_id: CAMERA},
    )
    result = index.resolve("aa:bb:cc:dd:ee:ff", "192.168.50.10")
    assert result == {
        "ha_mapped": True,
        "ha_device_id": "camera-device",
        "ha_device_name": "Office camera",
        "ha_area_id": "office",
        "ha_area_name": "Office",
        "ha_integrations": ["nest"],
        "ha_match_method": "device_registry_mac",
        "ha_match_confidence": "exact",
        "ha_device_url": "/config/devices/device/camera-device",
    }


def test_manual_mapping_wins_and_ip_is_a_weaker_fallback() -> None:
    index = OwnershipIndex(
        by_mac={"AA:BB:CC:DD:EE:FF": CAMERA},
        by_ip={"192.168.50.41": PRINTER},
        by_device_id={CAMERA.device_id: CAMERA, PRINTER.device_id: PRINTER},
    )
    manual = index.resolve(
        "AA:BB:CC:DD:EE:FF",
        "192.168.50.41",
        {"AA:BB:CC:DD:EE:FF": "printer-device"},
    )
    assert manual["ha_device_id"] == "printer-device"
    assert manual["ha_match_method"] == "manual_mac"
    assert manual["ha_match_confidence"] == "confirmed"

    ip_only = index.resolve("11:22:33:44:55:66", "192.168.50.41")
    assert ip_only["ha_device_id"] == "printer-device"
    assert ip_only["ha_match_method"] == "entity_ip"
    assert ip_only["ha_match_confidence"] == "probable"


def test_unmapped_client_is_explicit() -> None:
    result = OwnershipIndex({}, {}, {}).resolve(
        "84:72:07:EA:92:0D", "192.168.50.41"
    )
    assert result == {
        "ha_mapped": False,
        "ha_match_method": "unmapped",
        "ha_match_confidence": "none",
    }
