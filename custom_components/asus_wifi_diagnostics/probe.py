"""Validation for reports from Linux Wi-Fi probes."""

from __future__ import annotations

import re
from typing import Any

from .models import ProbeBss, ProbeSnapshot

MAX_NETWORKS = 128
MAX_PAYLOAD_BYTES = 256 * 1024

_BSSID = re.compile(r"^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$")
_PROBE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class InvalidProbePayload(ValueError):
    """Raised when a Wi-Fi probe sends malformed data."""


def _bounded_string(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise InvalidProbePayload(f"{field} must be a string")
    value = value.strip()
    if not value or len(value) > limit:
        raise InvalidProbePayload(f"{field} must contain 1-{limit} characters")
    return value


def _bounded_int(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidProbePayload(f"{field} must be an integer")
    if value < minimum or value > maximum:
        raise InvalidProbePayload(f"{field} must be between {minimum} and {maximum}")
    return value


def parse_probe_payload(payload: Any, received_at: str) -> ProbeSnapshot:
    """Validate and normalize a JSON probe report."""
    if not isinstance(payload, dict):
        raise InvalidProbePayload("payload must be an object")

    probe_id = _bounded_string(payload.get("probe_id"), "probe_id", 64).lower()
    if not _PROBE_ID.fullmatch(probe_id):
        raise InvalidProbePayload("probe_id contains unsupported characters")

    raw_networks = payload.get("networks")
    if not isinstance(raw_networks, list):
        raise InvalidProbePayload("networks must be a list")
    if len(raw_networks) > MAX_NETWORKS:
        raise InvalidProbePayload(f"networks cannot exceed {MAX_NETWORKS} entries")

    networks: list[ProbeBss] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_networks):
        if not isinstance(raw, dict):
            raise InvalidProbePayload(f"networks[{index}] must be an object")
        bssid = _bounded_string(raw.get("bssid"), f"networks[{index}].bssid", 17).upper()
        if not _BSSID.fullmatch(bssid):
            raise InvalidProbePayload(f"networks[{index}].bssid is invalid")
        if bssid in seen:
            continue
        seen.add(bssid)
        ssid = raw.get("ssid", "")
        if not isinstance(ssid, str) or len(ssid) > 64:
            raise InvalidProbePayload(f"networks[{index}].ssid is invalid")
        security = raw.get("security", "")
        if not isinstance(security, str) or len(security) > 128:
            raise InvalidProbePayload(f"networks[{index}].security is invalid")
        networks.append(
            ProbeBss(
                ssid=ssid.strip(),
                bssid=bssid,
                channel=_bounded_int(raw.get("channel"), "channel", 0, 233),
                frequency_mhz=_bounded_int(raw.get("frequency_mhz"), "frequency_mhz", 0, 100_000),
                signal_percent=_bounded_int(raw.get("signal_percent"), "signal_percent", 0, 100),
                security=security.strip(),
                in_use=raw.get("in_use") is True,
            )
        )

    networks.sort(key=lambda network: network.signal_percent, reverse=True)
    return ProbeSnapshot(
        probe_id=probe_id,
        name=_bounded_string(payload.get("name"), "name", 64),
        interface=_bounded_string(payload.get("interface"), "interface", 32),
        collected_at=_bounded_string(payload.get("collected_at"), "collected_at", 64),
        received_at=received_at,
        networks=tuple(networks),
    )
