"""ASUS Wi-Fi Diagnostics integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .api import AsusWifiDiagnosticsApi
from .const import (
    CONF_HOST_KEYS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    PLATFORMS,
)
from .coordinator import AsusWifiDiagnosticsCoordinator

type AsusWifiDiagnosticsConfigEntry = ConfigEntry[AsusWifiDiagnosticsCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: AsusWifiDiagnosticsConfigEntry
) -> bool:
    """Set up ASUS Wi-Fi Diagnostics from a config entry."""
    host_keys = dict(entry.data.get(CONF_HOST_KEYS, {}))

    def save_host_key(host: str, fingerprint: str) -> None:
        host_keys[host] = fingerprint
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_HOST_KEYS: host_keys}
        )

    api = AsusWifiDiagnosticsApi(
        host=entry.data[CONF_HOST],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        host_keys=host_keys,
        host_key_callback=save_host_key,
    )
    coordinator = AsusWifiDiagnosticsCoordinator(
        hass,
        api,
        timedelta(seconds=entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: AsusWifiDiagnosticsConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
