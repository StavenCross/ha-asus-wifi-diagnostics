"""ASUS Wi-Fi Diagnostics integration."""

from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus

from aiohttp.web import Request, Response
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .api import AsusWifiDiagnosticsApi
from .const import (
    CONF_CLIENT_OVERRIDES,
    CONF_HOST_KEYS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import AsusWifiDiagnosticsCoordinator
from .probe import MAX_PAYLOAD_BYTES, InvalidProbePayload, parse_probe_payload

type AsusWifiDiagnosticsConfigEntry = ConfigEntry[AsusWifiDiagnosticsCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: AsusWifiDiagnosticsConfigEntry) -> bool:
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
        manual_overrides=dict(entry.options.get(CONF_CLIENT_OVERRIDES, {})),
    )
    coordinator.webhook_id = f"{DOMAIN}_{entry.entry_id}"
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    webhook.async_register(
        hass,
        DOMAIN,
        "ASUS Wi-Fi Diagnostics probe",
        coordinator.webhook_id,
        _async_handle_probe_webhook,
        local_only=True,
        allowed_methods=("POST",),
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AsusWifiDiagnosticsConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        webhook.async_unregister(hass, entry.runtime_data.webhook_id)
    return unloaded


async def _async_handle_probe_webhook(
    hass: HomeAssistant, webhook_id: str, request: Request
) -> Response:
    """Accept a bounded report from a LAN-only Wi-Fi probe."""
    if request.content_length and request.content_length > MAX_PAYLOAD_BYTES:
        return Response(status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    try:
        payload = await request.json()
        entry = next(
            candidate
            for candidate in hass.config_entries.async_entries(DOMAIN)
            if candidate.runtime_data.webhook_id == webhook_id
        )
        report = parse_probe_payload(payload, dt_util.utcnow().isoformat())
    except (InvalidProbePayload, ValueError, StopIteration):
        return Response(status=HTTPStatus.BAD_REQUEST)
    entry.runtime_data.async_update_probe(report)
    return Response(status=HTTPStatus.NO_CONTENT)
