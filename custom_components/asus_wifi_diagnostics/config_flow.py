"""Config flow for ASUS Wi-Fi Diagnostics."""

from __future__ import annotations

import ipaddress
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import selector

from .api import (
    AsusWifiDiagnosticsApi,
    AuthenticationError,
    CannotConnectError,
    UnsupportedRouterError,
)
from .configuration import (
    AdditionalAccessPoint,
    additional_access_point_record,
    additional_access_points,
    monitored_client_record,
    monitored_clients,
)
from .const import (
    BAND_2_4_GHZ,
    CLIENT_BANDS,
    CONF_ACCESS_POINT_NAME,
    CONF_ADDITIONAL_ACCESS_POINTS,
    CONF_CLIENT_BAND,
    CONF_CLIENT_MAC,
    CONF_CLIENT_NAME,
    CONF_CLIENT_OVERRIDES,
    CONF_CRITICAL_UTILIZATION,
    CONF_HA_DEVICE_ID,
    CONF_HOST_KEYS,
    CONF_MONITORED_CLIENTS,
    CONF_OBSERVER_PROFILE,
    CONF_SCAN_INTERVAL,
    DEFAULT_CRITICAL_UTILIZATION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    OBSERVER_PROFILE_IOT_AP,
    OBSERVER_PROFILE_MAIN_MESH,
    OBSERVER_PROFILES,
)
from .models import MonitoredClient
from .ownership import normalize_mac


class AsusWifiDiagnosticsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the ASUS Wi-Fi Diagnostics config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> AsusWifiDiagnosticsOptionsFlow:
        """Create the options flow."""
        return AsusWifiDiagnosticsOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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
                for asusrouter_entry in self.hass.config_entries.async_entries("asusrouter"):
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
                vol.Optional(CONF_USERNAME, default=(user_input or {}).get(CONF_USERNAME, "")): str,
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


class AsusWifiDiagnosticsOptionsFlow(OptionsFlowWithReload):
    """Manage monitored clients and explicit standalone ASUS access points."""

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        """Show only the management actions applicable to current options."""
        options = ["add_client", "add_access_point"]
        if monitored_clients(self.config_entry.options):
            options.append("remove_client")
        if additional_access_points(self.config_entry.options):
            options.append("remove_access_point")
        return self.async_show_menu(step_id="init", menu_options=options)

    async def async_step_add_client(self, user_input=None) -> ConfigFlowResult:
        """Enroll one MAC with an optional HA device and explicit observer profile."""
        errors: dict[str, str] = {}
        if user_input is not None:
            mac = normalize_mac(user_input[CONF_CLIENT_MAC])
            device_id = str(user_input.get(CONF_HA_DEVICE_ID, "")).strip() or None
            if mac is None:
                errors[CONF_CLIENT_MAC] = "invalid_mac"
            elif device_id and dr.async_get(self.hass).async_get(device_id) is None:
                errors[CONF_HA_DEVICE_ID] = "device_not_found"
            else:
                options = dict(self.config_entry.options)
                clients = dict(options.get(CONF_MONITORED_CLIENTS, {}))
                client = MonitoredClient(
                    mac=mac,
                    name=str(user_input[CONF_CLIENT_NAME]).strip() or mac,
                    observer_profile=user_input[CONF_OBSERVER_PROFILE],
                    band=user_input[CONF_CLIENT_BAND],
                    ha_device_id=device_id,
                )
                clients[mac] = monitored_client_record(client)
                options[CONF_MONITORED_CLIENTS] = clients
                return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="add_client",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CLIENT_MAC): selector.TextSelector(),
                    vol.Required(CONF_CLIENT_NAME): selector.TextSelector(),
                    vol.Required(
                        CONF_OBSERVER_PROFILE, default=OBSERVER_PROFILE_IOT_AP
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(OBSERVER_PROFILES),
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(CONF_CLIENT_BAND, default=BAND_2_4_GHZ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(CLIENT_BANDS),
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(CONF_HA_DEVICE_ID): selector.DeviceSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_remove_client(self, user_input=None) -> ConfigFlowResult:
        """Remove one v0.8 or legacy monitored client without touching HA devices."""
        records = monitored_clients(self.config_entry.options)
        if user_input is not None:
            options = dict(self.config_entry.options)
            mac = user_input[CONF_CLIENT_MAC]
            clients = dict(options.get(CONF_MONITORED_CLIENTS, {}))
            clients.pop(mac, None)
            options[CONF_MONITORED_CLIENTS] = clients
            overrides = dict(options.get(CONF_CLIENT_OVERRIDES, {}))
            overrides.pop(mac, None)
            options[CONF_CLIENT_OVERRIDES] = overrides
            return self.async_create_entry(title="", data=options)

        choices = [
            {"value": mac, "label": f"{mac} - {client.name}"}
            for mac, client in sorted(records.items())
        ]
        return self.async_show_form(
            step_id="remove_client",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CLIENT_MAC): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=choices,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_add_access_point(self, user_input=None) -> ConfigFlowResult:
        """Validate and enroll one standalone ASUS AP through bounded read-only SSH."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                host = str(ipaddress.ip_address(str(user_input[CONF_HOST]).strip()))
            except ValueError:
                errors[CONF_HOST] = "invalid_host"
            else:
                existing = additional_access_points(self.config_entry.options)
                if host == self.config_entry.data[CONF_HOST] or host in existing:
                    errors[CONF_HOST] = "already_configured"
                else:
                    host_keys = dict(self.config_entry.data.get(CONF_HOST_KEYS, {}))

                    def record_key(key_host: str, fingerprint: str) -> None:
                        host_keys[key_host] = fingerprint

                    api = AsusWifiDiagnosticsApi(
                        host=self.config_entry.data[CONF_HOST],
                        username=self.config_entry.data[CONF_USERNAME],
                        password=self.config_entry.data[CONF_PASSWORD],
                        host_keys=host_keys,
                        host_key_callback=record_key,
                    )
                    try:
                        await api.discover_standalone_access_point(
                            host, user_input[CONF_OBSERVER_PROFILE]
                        )
                    except AuthenticationError:
                        errors["base"] = "invalid_auth"
                    except UnsupportedRouterError:
                        errors["base"] = "unsupported_router"
                    except CannotConnectError:
                        errors["base"] = "cannot_connect"
                    except Exception:
                        errors["base"] = "unknown"
                    else:
                        self.hass.config_entries.async_update_entry(
                            self.config_entry,
                            data={**self.config_entry.data, CONF_HOST_KEYS: host_keys},
                        )
                        options = dict(self.config_entry.options)
                        access_points = dict(options.get(CONF_ADDITIONAL_ACCESS_POINTS, {}))
                        access_point = AdditionalAccessPoint(
                            host=host,
                            name=str(user_input[CONF_ACCESS_POINT_NAME]).strip() or host,
                            observer_profile=user_input[CONF_OBSERVER_PROFILE],
                        )
                        access_points[host] = additional_access_point_record(access_point)
                        options[CONF_ADDITIONAL_ACCESS_POINTS] = access_points
                        return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="add_access_point",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): selector.TextSelector(),
                    vol.Required(CONF_ACCESS_POINT_NAME): selector.TextSelector(),
                    vol.Required(
                        CONF_OBSERVER_PROFILE, default=OBSERVER_PROFILE_IOT_AP
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[OBSERVER_PROFILE_MAIN_MESH, OBSERVER_PROFILE_IOT_AP],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_remove_access_point(self, user_input=None) -> ConfigFlowResult:
        """Remove one explicit AP target while preserving its learned host key."""
        records = additional_access_points(self.config_entry.options)
        if user_input is not None:
            options = dict(self.config_entry.options)
            access_points = dict(options.get(CONF_ADDITIONAL_ACCESS_POINTS, {}))
            access_points.pop(user_input[CONF_HOST], None)
            options[CONF_ADDITIONAL_ACCESS_POINTS] = access_points
            return self.async_create_entry(title="", data=options)

        choices = [
            {"value": host, "label": f"{access_point.name} - {host}"}
            for host, access_point in sorted(records.items())
        ]
        return self.async_show_form(
            step_id="remove_access_point",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=choices,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_add_mapping(self, user_input=None) -> ConfigFlowResult:
        """Route an in-progress legacy flow to the monitored-client form."""
        return await self.async_step_add_client(user_input)

    async def async_step_remove_mapping(self, user_input=None) -> ConfigFlowResult:
        """Route an in-progress legacy removal flow to the monitored-client form."""
        return await self.async_step_remove_client(user_input)
