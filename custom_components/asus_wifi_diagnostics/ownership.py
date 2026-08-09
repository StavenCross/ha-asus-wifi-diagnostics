"""Join router clients to Home Assistant-owned devices."""

from __future__ import annotations

import re
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse

_MAC_RE = re.compile(r"^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$")
_MAC_ATTRIBUTE_KEYS = ("mac", "mac_address", "device_mac")
_IP_ATTRIBUTE_KEYS = ("ip", "ip_address", "host")


def normalize_mac(value: str | None) -> str | None:
    """Return a canonical MAC address or None."""
    if not value:
        return None
    candidate = value.strip().replace("-", ":").upper()
    return candidate if _MAC_RE.fullmatch(candidate) else None


def normalize_ip(value: str | None) -> str | None:
    """Return a canonical IP address or None."""
    if not value:
        return None
    try:
        return str(ip_address(value.strip()))
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class OwnershipRecord:
    """A Home Assistant device that can own a network client."""

    device_id: str
    name: str
    area_id: str | None = None
    area_name: str | None = None
    integrations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OwnershipIndex:
    """Unique exact-match indexes for Home Assistant devices."""

    by_mac: dict[str, OwnershipRecord]
    by_ip: dict[str, OwnershipRecord]
    by_device_id: dict[str, OwnershipRecord]

    def resolve(
        self,
        mac: str | None,
        ip: str | None,
        manual_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Return bounded ownership attributes for a network client."""
        canonical_mac = normalize_mac(mac)
        canonical_ip = normalize_ip(ip)
        record = None
        method = "unmapped"
        confidence = "none"

        if canonical_mac and manual_overrides:
            device_id = manual_overrides.get(canonical_mac)
            if device_id:
                record = self.by_device_id.get(device_id)
                if record:
                    method = "manual_mac"
                    confidence = "confirmed"
        if record is None and canonical_mac:
            record = self.by_mac.get(canonical_mac)
            if record:
                method = "device_registry_mac"
                confidence = "exact"
        if record is None and canonical_ip:
            record = self.by_ip.get(canonical_ip)
            if record:
                method = "entity_ip"
                confidence = "probable"

        if record is None:
            return {
                "ha_mapped": False,
                "ha_match_method": method,
                "ha_match_confidence": confidence,
            }
        return {
            "ha_mapped": True,
            "ha_device_id": record.device_id,
            "ha_device_name": record.name,
            "ha_area_id": record.area_id,
            "ha_area_name": record.area_name,
            "ha_integrations": list(record.integrations),
            "ha_match_method": method,
            "ha_match_confidence": confidence,
            "ha_device_url": f"/config/devices/device/{record.device_id}",
        }


def _unique_records(
    candidates: dict[str, list[OwnershipRecord]],
) -> dict[str, OwnershipRecord]:
    """Keep only identities that resolve to one HA device."""
    result: dict[str, OwnershipRecord] = {}
    for identity, records in candidates.items():
        unique = {record.device_id: record for record in records}
        if len(unique) == 1:
            result[identity] = next(iter(unique.values()))
    return result


def build_ownership_index(hass) -> OwnershipIndex:
    """Build a conservative index from HA device/entity registries and live states."""
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    area_registry = ar.async_get(hass)
    entities_by_device: dict[str, list[Any]] = {}
    for entity in entity_registry.entities.values():
        if entity.device_id:
            entities_by_device.setdefault(entity.device_id, []).append(entity)

    mac_candidates: dict[str, list[OwnershipRecord]] = {}
    ip_candidates: dict[str, list[OwnershipRecord]] = {}
    by_device_id: dict[str, OwnershipRecord] = {}

    for device in device_registry.devices.values():
        entities = entities_by_device.get(device.id, [])
        area_id = device.area_id or next(
            (entity.area_id for entity in entities if entity.area_id), None
        )
        area = area_registry.async_get_area(area_id) if area_id else None
        record = OwnershipRecord(
            device_id=device.id,
            name=device.name_by_user or device.name or device.id,
            area_id=area_id,
            area_name=area.name if area else None,
            integrations=tuple(sorted({entity.platform for entity in entities})),
        )
        by_device_id[device.id] = record

        for connection_type, value in device.connections:
            if connection_type == dr.CONNECTION_NETWORK_MAC and (
                mac := normalize_mac(value)
            ):
                mac_candidates.setdefault(mac, []).append(record)

        for entity in entities:
            state = hass.states.get(entity.entity_id)
            if state is None:
                continue
            for key in _MAC_ATTRIBUTE_KEYS:
                if mac := normalize_mac(state.attributes.get(key)):
                    mac_candidates.setdefault(mac, []).append(record)
            for key in _IP_ATTRIBUTE_KEYS:
                if address := normalize_ip(state.attributes.get(key)):
                    ip_candidates.setdefault(address, []).append(record)

        if device.configuration_url:
            hostname = urlparse(str(device.configuration_url)).hostname
            if address := normalize_ip(hostname):
                ip_candidates.setdefault(address, []).append(record)

    return OwnershipIndex(
        by_mac=_unique_records(mac_candidates),
        by_ip=_unique_records(ip_candidates),
        by_device_id=by_device_id,
    )
