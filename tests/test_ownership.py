"""Tests for conservative Home Assistant device ownership matching."""

from custom_components.asus_wifi_diagnostics.ownership import (
    OwnershipIndex,
    OwnershipRecord,
    _unique_records,
    macs_in_identifier,
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
    assert normalize_mac("aabbccddeeff") == "AA:BB:CC:DD:EE:FF"
    assert normalize_ip("192.168.50.41") == "192.168.50.41"
    assert normalize_ip("printer.local") is None
    assert macs_in_identifier("cfe92100-67c4-11d4-a45f-6855d433cf42") == {"68:55:D4:33:CF:42"}


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
    result = OwnershipIndex({}, {}, {}).resolve("84:72:07:EA:92:0D", "192.168.50.41")
    assert result == {
        "ha_mapped": False,
        "ha_match_method": "unmapped",
        "ha_match_confidence": "none",
        "ha_suggestion_count": 0,
    }


def test_network_discovery_duplicate_does_not_hide_real_owner() -> None:
    network_copy = OwnershipRecord(
        device_id="network-copy",
        name="Office camera tracker",
        integrations=("asusrouter",),
    )
    result = _unique_records({"AA:BB:CC:DD:EE:FF": [CAMERA, network_copy]})
    assert result["AA:BB:CC:DD:EE:FF"] == CAMERA


def test_unique_model_suggestion_is_review_only() -> None:
    garage_switch = OwnershipRecord(
        device_id="garage-switch",
        name="garage switch",
        area_id="garage",
        area_name="Garage",
        integrations=("smartthings",),
        manufacturer="TP-LINK",
        model="ES20M(US)",
    )
    index = OwnershipIndex({}, {}, {garage_switch.device_id: garage_switch})
    result = index.resolve("28:87:BA:87:8E:30", "192.168.50.204", name="ES20M")
    assert result["ha_mapped"] is False
    assert result["ha_suggestion_count"] == 1
    assert result["ha_suggestions"][0]["ha_device_id"] == "garage-switch"
    assert result["ha_suggestions"][0]["score"] == 85
    assert result["ha_suggestions"][0]["evidence"] == ["exact model in network name"]


def test_ambiguous_model_returns_ranked_candidates_without_mapping() -> None:
    attic = OwnershipRecord(
        device_id="attic",
        name="attic lights",
        area_id="attic",
        integrations=("smartthings",),
        manufacturer="TP-LINK",
        model="KP405(US)",
    )
    pool = OwnershipRecord(
        device_id="pool",
        name="Pool Filter",
        integrations=("smartthings",),
        manufacturer="TP-LINK",
        model="KP405(US)",
    )
    index = OwnershipIndex({}, {}, {attic.device_id: attic, pool.device_id: pool})
    result = index.resolve("5C:E9:31:7B:7A:73", None, name="KP405")
    assert result["ha_mapped"] is False
    assert result["ha_suggestion_count"] == 2
    assert {item["ha_device_id"] for item in result["ha_suggestions"]} == {
        "attic",
        "pool",
    }


def test_node_area_ranks_but_does_not_confirm_ambiguous_thermostat() -> None:
    living = OwnershipRecord(
        device_id="living",
        name="Living Room Thermostat",
        area_id="living_room",
        integrations=("nest",),
        manufacturer="Google Nest",
        model="Thermostat",
    )
    loft = OwnershipRecord(
        device_id="loft",
        name="Loft Thermostat",
        area_id="loft",
        integrations=("nest",),
        manufacturer="Google Nest",
        model="Thermostat",
    )
    index = OwnershipIndex({}, {}, {living.device_id: living, loft.device_id: loft})
    suggestions = index.suggest("Nest-Thermostat-F5CC", "living_room")
    assert [item["ha_device_id"] for item in suggestions] == ["living", "loft"]
    assert suggestions[0]["score"] == 95
    assert suggestions[1]["score"] == 85


def test_unique_base_station_root_is_suggested() -> None:
    root = OwnershipRecord(
        device_id="system",
        name="Home security",
        integrations=("simplisafe",),
        manufacturer="SimpliSafe",
        model="3",
    )
    keypad = OwnershipRecord(
        device_id="keypad",
        name="Keypad",
        integrations=("simplisafe",),
        manufacturer="SimpliSafe",
        model="Keypad",
        via_device_id="system",
    )
    index = OwnershipIndex({}, {}, {root.device_id: root, keypad.device_id: keypad})
    suggestions = index.suggest("SimpliSafe_Basestation")
    assert len(suggestions) == 1
    assert suggestions[0]["ha_device_id"] == "system"
    assert suggestions[0]["score"] == 95


def test_manufacturer_and_area_alone_do_not_suggest_sibling_devices() -> None:
    curtain = OwnershipRecord(
        device_id="curtain",
        name="Back curtain",
        area_id="living_room",
        integrations=("switchbot_cloud",),
        manufacturer="SwitchBot",
        model="Curtain3",
    )
    index = OwnershipIndex({}, {}, {curtain.device_id: curtain})
    assert index.suggest("SwitchBot-HubMini-CCB511", "living_room") == []


def test_more_specific_compound_device_name_wins() -> None:
    dishwasher = OwnershipRecord(
        device_id="dishwasher",
        name="Dishwasher",
        integrations=("lg_thinq",),
        manufacturer="LGE",
    )
    washer = OwnershipRecord(
        device_id="washer",
        name="Washer",
        integrations=("smartthings",),
        manufacturer="LGE",
    )
    index = OwnershipIndex({}, {}, {dishwasher.device_id: dishwasher, washer.device_id: washer})
    suggestions = index.suggest("LG_Smart_DishWasher2_open")
    assert [item["ha_device_id"] for item in suggestions] == ["dishwasher"]
