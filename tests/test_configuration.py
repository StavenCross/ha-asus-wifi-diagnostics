"""Regression coverage for portable v0.8 configuration normalization."""

from custom_components.asus_wifi_diagnostics.configuration import (
    additional_access_points,
    monitored_clients,
)
from custom_components.asus_wifi_diagnostics.const import (
    BAND_2_4_GHZ,
    CONF_ACCESS_POINT_NAME,
    CONF_ADDITIONAL_ACCESS_POINTS,
    CONF_CLIENT_BAND,
    CONF_CLIENT_NAME,
    CONF_CLIENT_OVERRIDES,
    CONF_HA_DEVICE_ID,
    CONF_MONITORED_CLIENTS,
    CONF_OBSERVER_PROFILE,
    OBSERVER_PROFILE_IOT_AP,
)


def test_legacy_manual_mapping_remains_a_monitored_client() -> None:
    """A v0.7 config entry keeps its entity identity and conservative observer scope."""
    clients = monitored_clients({CONF_CLIENT_OVERRIDES: {"aa:bb:cc:dd:ee:ff": "device-id"}})

    client = clients["AA:BB:CC:DD:EE:FF"]
    assert client.ha_device_id == "device-id"
    assert client.observer_profile == "all_client_aps"
    assert client.band == "any"


def test_v08_client_overlays_legacy_record() -> None:
    """An explicit v0.8 record supplies the narrow profile without deleting rollback data."""
    clients = monitored_clients(
        {
            CONF_CLIENT_OVERRIDES: {"AA:BB:CC:DD:EE:FF": "old-device"},
            CONF_MONITORED_CLIENTS: {
                "AA:BB:CC:DD:EE:FF": {
                    CONF_CLIENT_NAME: "Pantry light",
                    CONF_OBSERVER_PROFILE: OBSERVER_PROFILE_IOT_AP,
                    CONF_CLIENT_BAND: BAND_2_4_GHZ,
                    CONF_HA_DEVICE_ID: "new-device",
                }
            },
        }
    )

    client = clients["AA:BB:CC:DD:EE:FF"]
    assert client.name == "Pantry light"
    assert client.ha_device_id == "new-device"
    assert client.observer_profile == OBSERVER_PROFILE_IOT_AP


def test_additional_access_point_rejects_all_observer_profile() -> None:
    """A physical AP must own one concrete observer group, never the aggregate selector."""
    access_points = additional_access_points(
        {
            CONF_ADDITIONAL_ACCESS_POINTS: {
                "192.168.50.168": {
                    CONF_ACCESS_POINT_NAME: "IoT AP",
                    CONF_OBSERVER_PROFILE: "all_client_aps",
                },
                "192.168.50.169": {
                    CONF_ACCESS_POINT_NAME: "Valid IoT AP",
                    CONF_OBSERVER_PROFILE: OBSERVER_PROFILE_IOT_AP,
                },
                "not-an-address": {
                    CONF_ACCESS_POINT_NAME: "Invalid AP",
                    CONF_OBSERVER_PROFILE: OBSERVER_PROFILE_IOT_AP,
                },
            }
        }
    )

    assert set(access_points) == {"192.168.50.169"}
