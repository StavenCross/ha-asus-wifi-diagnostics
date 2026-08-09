#!/usr/bin/env python3
"""Report a NetworkManager Wi-Fi survey to ASUS Wi-Fi Diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime


def split_nmcli_terse(line: str) -> list[str]:
    """Split an nmcli terse row while preserving escaped separators."""
    values: list[str] = []
    current: list[str] = []
    escaped = False
    for character in line.rstrip("\n"):
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            values.append("".join(current))
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    values.append("".join(current))
    return values


def collect(interface: str, probe_name: str) -> dict[str, object]:
    """Run one NetworkManager survey and return a webhook payload."""
    command = [
        "nmcli",
        "-t",
        "--escape",
        "yes",
        "-f",
        "IN-USE,SSID,BSSID,CHAN,FREQ,SIGNAL,SECURITY",
        "device",
        "wifi",
        "list",
        "--rescan",
        "yes",
        "ifname",
        interface,
    ]
    result = subprocess.run(command, capture_output=True, check=True, text=True, timeout=45)
    networks: dict[str, dict[str, object]] = {}
    for line in result.stdout.splitlines():
        values = split_nmcli_terse(line)
        if len(values) != 7:
            continue
        in_use, ssid, bssid, channel, frequency, signal, security = values
        try:
            normalized = {
                "ssid": "" if ssid == "--" else ssid,
                "bssid": bssid.upper(),
                "channel": int(channel),
                "frequency_mhz": int(frequency.split()[0]),
                "signal_percent": int(signal),
                "security": "" if security == "--" else security,
                "in_use": in_use == "*",
            }
        except ValueError:
            continue
        previous = networks.get(bssid)
        if previous is None or normalized["signal_percent"] > previous["signal_percent"]:
            networks[bssid] = normalized
    return {
        "probe_id": "couchcast",
        "name": probe_name,
        "interface": interface,
        "collected_at": datetime.now(UTC).isoformat(),
        "networks": sorted(
            networks.values(), key=lambda network: network["signal_percent"], reverse=True
        )[:128],
    }


def post(webhook_url: str, payload: dict[str, object]) -> None:
    """Deliver one report to Home Assistant."""
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "couchcast-wifi-probe/1"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status not in (200, 204):
            raise RuntimeError(f"Home Assistant returned HTTP {response.status}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interface", default=os.getenv("HA_WIFI_PROBE_INTERFACE", "wlp7s0"))
    parser.add_argument("--name", default=os.getenv("HA_WIFI_PROBE_NAME", "CouchCast PC"))
    args = parser.parse_args()
    webhook_url = os.getenv("HA_WIFI_PROBE_WEBHOOK_URL")
    if not webhook_url:
        parser.error("HA_WIFI_PROBE_WEBHOOK_URL is required")
    try:
        post(webhook_url, collect(args.interface, args.name))
    except (OSError, RuntimeError, subprocess.SubprocessError) as err:
        print(f"Wi-Fi probe failed: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
