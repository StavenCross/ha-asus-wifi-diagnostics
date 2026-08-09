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

DEFAULT_SCAN_INTERVAL = 30
DEFAULT_CRITICAL_UTILIZATION = 90
MIN_SCAN_INTERVAL = 15
DISCOVERY_INTERVAL = timedelta(minutes=10)

MANUFACTURER = "ASUS"

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
