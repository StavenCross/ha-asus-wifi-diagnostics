"""Config flow for ASUS Wi-Fi Diagnostics."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME

from .api import (
    AsusWifiDiagnosticsApi,
    AuthenticationError,
    CannotConnectError,
    UnsupportedRouterError,
)
from .const import (
    CONF_CRITICAL_UTILIZATION,
    CONF_HOST_KEYS,
    CONF_SCAN_INTERVAL,
    DEFAULT_CRITICAL_UTILIZATION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)


class AsusWifiDiagnosticsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the ASUS Wi-Fi Diagnostics config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle initial setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip().lower()
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()
            fingerprints: dict[str, str] = {}

            username = user_input.get(CONF_USERNAME, "").strip()
            password = user_input.get(CONF_PASSWORD, "")
            if not username or not password:
                for asusrouter_entry in self.hass.config_entries.async_entries(
                    "asusrouter"
                ):
                    if str(asusrouter_entry.data.get(CONF_HOST, "")).lower() != host:
                        continue
                    credentials = {
                        **asusrouter_entry.data,
                        **asusrouter_entry.options,
                    }
                    username = username or credentials.get(CONF_USERNAME, "")
                    password = password or credentials.get(CONF_PASSWORD, "")
                    break

            if not username or not password:
                errors["base"] = "missing_credentials"

            data = {
                **user_input,
                CONF_HOST: host,
                CONF_USERNAME: username,
                CONF_PASSWORD: password,
            }

            def record_key(key_host: str, fingerprint: str) -> None:
                fingerprints[key_host] = fingerprint

            if not errors:
                api = AsusWifiDiagnosticsApi(
                    host=host,
                    username=username,
                    password=password,
                    host_key_callback=record_key,
                )
                try:
                    await api.discover_nodes()
                except AuthenticationError:
                    errors["base"] = "invalid_auth"
                except UnsupportedRouterError:
                    errors["base"] = "unsupported_router"
                except CannotConnectError:
                    errors["base"] = "cannot_connect"
                except Exception:
                    errors["base"] = "unknown"
                else:
                    return self.async_create_entry(
                        title=f"ASUS Wi-Fi Diagnostics ({host})",
                        data={**data, CONF_HOST_KEYS: fingerprints},
                    )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=(user_input or {}).get(CONF_HOST, "")): str,
                vol.Optional(
                    CONF_USERNAME, default=(user_input or {}).get(CONF_USERNAME, "")
                ): str,
                vol.Optional(CONF_PASSWORD, default=""): str,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=300)
                ),
                vol.Optional(
                    CONF_CRITICAL_UTILIZATION, default=DEFAULT_CRITICAL_UTILIZATION
                ): vol.All(vol.Coerce(int), vol.Range(min=70, max=100)),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
