"""Normalize portable access-point and monitored-client configuration.

The integration originally stored only manual MAC-to-device ownership overrides. This module owns
the backward-compatible read boundary so runtime and entities consume one typed configuration while
existing config entries and entity unique IDs remain valid.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .const import (
    BAND_2_4_GHZ,
    CLIENT_BANDS,
    CONF_ACCESS_POINT_NAME,
    CONF_ADDITIONAL_ACCESS_POINTS,
    CONF_CLIENT_BAND,
    CONF_CLIENT_NAME,
    CONF_CLIENT_OVERRIDES,
    CONF_HA_DEVICE_ID,
    CONF_MONITORED_CLIENTS,
    CONF_OBSERVER_PROFILE,
    OBSERVER_PROFILE_ALL,
    OBSERVER_PROFILE_IOT_AP,
    OBSERVER_PROFILES,
)
from .models import MonitoredClient
from .ownership import normalize_mac


@dataclass(frozen=True, slots=True)
class AdditionalAccessPoint:
    """Describe one explicitly configured standalone ASUS access point."""

    host: str
    name: str
    observer_profile: str


def monitored_clients(options: Mapping[str, Any]) -> dict[str, MonitoredClient]:
    """Return legacy and v0.8 client enrollment as one validated MAC-keyed map.

    Legacy manual mappings remain first-class monitored clients. New records overlay them without
    deleting the old option so rollback to v0.7.1 remains recoverable.
    """
    clients: dict[str, MonitoredClient] = {}
    for raw_mac, raw_device_id in options.get(CONF_CLIENT_OVERRIDES, {}).items():
        mac = normalize_mac(raw_mac)
        if mac is None:
            continue
        clients[mac] = MonitoredClient(
            mac=mac,
            name=mac,
            observer_profile=OBSERVER_PROFILE_ALL,
            band="any",
            ha_device_id=str(raw_device_id) or None,
        )

    for raw_mac, raw_record in options.get(CONF_MONITORED_CLIENTS, {}).items():
        mac = normalize_mac(raw_mac)
        if mac is None or not isinstance(raw_record, Mapping):
            continue
        profile = str(raw_record.get(CONF_OBSERVER_PROFILE, OBSERVER_PROFILE_ALL))
        band = str(raw_record.get(CONF_CLIENT_BAND, BAND_2_4_GHZ))
        if profile not in OBSERVER_PROFILES or band not in CLIENT_BANDS:
            continue
        clients[mac] = MonitoredClient(
            mac=mac,
            name=str(raw_record.get(CONF_CLIENT_NAME, mac)).strip() or mac,
            observer_profile=profile,
            band=band,
            ha_device_id=str(raw_record.get(CONF_HA_DEVICE_ID, "")).strip() or None,
        )
    return clients


def additional_access_points(options: Mapping[str, Any]) -> dict[str, AdditionalAccessPoint]:
    """Return validated standalone AP targets keyed by normalized host text."""
    access_points: dict[str, AdditionalAccessPoint] = {}
    for raw_host, raw_record in options.get(CONF_ADDITIONAL_ACCESS_POINTS, {}).items():
        if not isinstance(raw_record, Mapping):
            continue
        try:
            host = str(ipaddress.ip_address(str(raw_host).strip()))
        except ValueError:
            continue
        profile = str(raw_record.get(CONF_OBSERVER_PROFILE, OBSERVER_PROFILE_IOT_AP))
        if not host or profile not in OBSERVER_PROFILES or profile == OBSERVER_PROFILE_ALL:
            continue
        access_points[host] = AdditionalAccessPoint(
            host=host,
            name=str(raw_record.get(CONF_ACCESS_POINT_NAME, host)).strip() or host,
            observer_profile=profile,
        )
    return access_points


def monitored_client_record(client: MonitoredClient) -> dict[str, str]:
    """Serialize one monitored client into config-entry options."""
    record = {
        CONF_CLIENT_NAME: client.name,
        CONF_OBSERVER_PROFILE: client.observer_profile,
        CONF_CLIENT_BAND: client.band,
    }
    if client.ha_device_id:
        record[CONF_HA_DEVICE_ID] = client.ha_device_id
    return record


def additional_access_point_record(access_point: AdditionalAccessPoint) -> dict[str, str]:
    """Serialize one standalone access point into config-entry options."""
    return {
        CONF_ACCESS_POINT_NAME: access_point.name,
        CONF_OBSERVER_PROFILE: access_point.observer_profile,
    }
