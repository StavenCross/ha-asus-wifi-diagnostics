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
    if re.fullmatch(r"[0-9A-F]{12}", candidate):
        candidate = ":".join(candidate[index : index + 2] for index in range(0, 12, 2))
    return candidate if _MAC_RE.fullmatch(candidate) else None


def macs_in_identifier(value: str) -> set[str]:
    """Extract complete MAC identities embedded in an integration identifier."""
    compact_matches = re.findall(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{12})(?![0-9A-Fa-f])", value)
    delimited_matches = re.findall(
        r"(?<![0-9A-Fa-f])((?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2})(?![0-9A-Fa-f])",
        value,
    )
    return {
        mac
        for candidate in [*compact_matches, *delimited_matches]
        if (mac := normalize_mac(candidate))
    }


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
    manufacturer: str | None = None
    model: str | None = None
    via_device_id: str | None = None


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
        name: str | None = None,
        node_area_id: str | None = None,
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
            suggestions = self.suggest(name, node_area_id)
            result = {
                "ha_mapped": False,
                "ha_match_method": method,
                "ha_match_confidence": confidence,
                "ha_suggestion_count": len(suggestions),
            }
            if suggestions:
                result["ha_suggestions"] = suggestions
            return result
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

    def suggest(
        self, name: str | None, node_area_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Rank review-only HA device candidates from a router hostname."""
        client = _compact(name)
        if len(client) < 4 or client in {"connect", "unknown", "wlan0"}:
            return []

        owned = [
            record
            for record in self.by_device_id.values()
            if set(record.integrations) - {"asusrouter", "asus_wifi_diagnostics"}
        ]
        scored: list[tuple[int, OwnershipRecord, list[str]]] = []
        for record in owned:
            score = 0
            evidence: list[str] = []
            device_name = _compact(record.name)
            model = _compact(record.model)
            manufacturer = _compact(record.manufacturer)

            if client == device_name:
                score = 100
                evidence.append("exact device name")
            elif len(device_name) >= 5 and (
                device_name in client or client in device_name
            ):
                score = 90
                evidence.append("device name appears in network name")

            if len(model) >= 4 and (model in client or client in model):
                score = max(score, 85)
                evidence.append("exact model in network name")

            manufacturer_tokens = _terms(record.manufacturer)
            client_tokens = _terms(name)
            if manufacturer and (
                manufacturer in client or manufacturer_tokens & client_tokens
            ):
                score = max(score, 55)
                evidence.append("manufacturer in network name")

            if score >= 85 and node_area_id and record.area_id == node_area_id:
                score += 10
                evidence.append("same area as current mesh node")
            if score >= 65:
                scored.append((min(score, 100), record, evidence))

        # A base-station/gateway hostname can identify a unique integration root,
        # but only when sibling devices explicitly point to that root.
        if any(term in client for term in ("basestation", "gateway", "bridge")):
            manufacturer_matches = [
                record
                for record in owned
                if _compact(record.manufacturer)
                and (
                    _compact(record.manufacturer) in client
                    or _terms(record.manufacturer) & _terms(name)
                )
            ]
            roots = [
                record
                for record in manufacturer_matches
                if record.via_device_id is None
                and any(
                    child.via_device_id == record.device_id
                    for child in manufacturer_matches
                )
            ]
            if len(roots) == 1:
                root = roots[0]
                scored = [item for item in scored if item[1].device_id != root.device_id]
                scored.append(
                    (95, root, ["unique integration root for base station hostname"])
                )

        # Prefer the more specific device name when both a compound name and
        # one of its component words match (for example Dishwasher vs Washer).
        scored = [
            item
            for item in scored
            if not any(
                item[1].device_id != other[1].device_id
                and len(_compact(item[1].name)) < len(_compact(other[1].name))
                and _compact(item[1].name) in _compact(other[1].name)
                and item[0] <= other[0]
                for other in scored
            )
        ]

        scored.sort(key=lambda item: (-item[0], item[1].name.casefold()))
        return [
            {
                "ha_device_id": record.device_id,
                "ha_device_name": record.name,
                "ha_area_id": record.area_id,
                "ha_area_name": record.area_name,
                "ha_integrations": list(record.integrations),
                "score": score,
                "evidence": evidence,
                "ha_device_url": f"/config/devices/device/{record.device_id}",
            }
            for score, record, evidence in scored[:3]
        ]


def _compact(value: str | None) -> str:
    """Return lowercase alphanumeric identity text."""
    return re.sub(r"[^a-z0-9]", "", value.casefold()) if value else ""


def _terms(value: str | None) -> set[str]:
    """Return useful lowercase identity terms, including camel-case words."""
    if not value:
        return set()
    split = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    return {
        term.casefold()
        for term in re.findall(r"[A-Za-z]+", split)
        if len(term) >= 3
    }


def _unique_records(
    candidates: dict[str, list[OwnershipRecord]],
) -> dict[str, OwnershipRecord]:
    """Keep identities with one non-network-source HA owner."""
    result: dict[str, OwnershipRecord] = {}
    for identity, records in candidates.items():
        unique = {
            record.device_id: record
            for record in records
            if set(record.integrations) - {"asusrouter", "asus_wifi_diagnostics"}
        }
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
        identifier_integrations = {
            str(integration) for integration, _ in device.identifiers
        }
        record = OwnershipRecord(
            device_id=device.id,
            name=device.name_by_user or device.name or device.id,
            area_id=area_id,
            area_name=area.name if area else None,
            integrations=tuple(
                sorted(
                    {entity.platform for entity in entities}
                    | identifier_integrations
                )
            ),
            manufacturer=device.manufacturer,
            model=device.model,
            via_device_id=device.via_device_id,
        )
        by_device_id[device.id] = record

        for connection_type, value in device.connections:
            if connection_type == dr.CONNECTION_NETWORK_MAC and (
                mac := normalize_mac(value)
            ):
                mac_candidates.setdefault(mac, []).append(record)

        for _, identifier in device.identifiers:
            for mac in macs_in_identifier(identifier):
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
