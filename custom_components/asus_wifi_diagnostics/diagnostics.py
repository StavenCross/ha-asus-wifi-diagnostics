"""Diagnostics support for ASUS Wi-Fi Diagnostics."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import AsusWifiDiagnosticsConfigEntry

TO_REDACT = {"password", "host_keys"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AsusWifiDiagnosticsConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostics."""
    coordinator = entry.runtime_data
    return {
        "config": async_redact_data(dict(entry.data), TO_REDACT),
        "snapshot": asdict(coordinator.data) if coordinator.data else None,
    }

