"""Constants for ASUS Wi-Fi Diagnostics."""

from datetime import timedelta

DOMAIN = "asus_wifi_diagnostics"
PLATFORMS = ["sensor", "binary_sensor", "event"]

CONF_SCAN_INTERVAL = "scan_interval"
CONF_CRITICAL_UTILIZATION = "critical_utilization"
CONF_HOST_KEYS = "host_keys"
CONF_CLIENT_OVERRIDES = "client_overrides"
CONF_CLIENT_MAC = "client_mac"
CONF_HA_DEVICE_ID = "ha_device_id"
CONF_MONITORED_CLIENTS = "monitored_clients"
CONF_CLIENT_NAME = "client_name"
CONF_OBSERVER_PROFILE = "observer_profile"
CONF_CLIENT_BAND = "client_band"
CONF_ADDITIONAL_ACCESS_POINTS = "additional_access_points"
CONF_ACCESS_POINT_NAME = "access_point_name"

DEFAULT_SCAN_INTERVAL = 30
DEFAULT_CRITICAL_UTILIZATION = 90
MIN_SCAN_INTERVAL = 15
DISCOVERY_INTERVAL = timedelta(minutes=10)

MANUFACTURER = "ASUS"
BAND_2_4_GHZ = "2_4_ghz"
BAND_5_GHZ = "5_ghz"

OBSERVER_PROFILE_MAIN_MESH = "main_mesh"
OBSERVER_PROFILE_IOT_AP = "iot_ap"
OBSERVER_PROFILE_ALL = "all_client_aps"
OBSERVER_PROFILES = (
    OBSERVER_PROFILE_MAIN_MESH,
    OBSERVER_PROFILE_IOT_AP,
    OBSERVER_PROFILE_ALL,
)

CLIENT_BAND_ANY = "any"
CLIENT_BANDS = (BAND_2_4_GHZ, BAND_5_GHZ, CLIENT_BAND_ANY)
PRESENCE_CONTRACT_VERSION = 1

# ASUSWRT uses physical interfaces on the controller and a virtual BSS on
# AiMesh nodes. Restrict commands to known interfaces: probing arbitrary wl
# interfaces can crash wl on some firmware builds.
RADIO_INTERFACES = {
    "GT6": "eth6",
    "GT10": "eth6",
    "ZENWIFI_XT8": "eth4",
    "XT8": "eth4",
    "XT8_V2": "eth4",
    "RT-AX95Q": "eth4",
}

# The second 5 GHz interface on these tri-band models carries the dedicated
# AiMesh backhaul SSID. Poll only the client-facing 5 GHz interface here.
RADIO_5_GHZ_INTERFACES = {
    "GT6": "eth4",
    "GT10": "eth4",
    "ZENWIFI_XT8": "eth5",
    "XT8": "eth5",
    "XT8_V2": "eth5",
    "RT-AX95Q": "eth5",
}
