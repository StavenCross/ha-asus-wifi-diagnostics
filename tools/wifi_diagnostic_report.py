#!/usr/bin/env python3
"""Generate a read-only, time-bounded Wi-Fi diagnostic report from Home Assistant."""

from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

METRIC_KEYS = {
    "utilization",
    "overlapping_wifi",
    "transmit_airtime",
    "own_wifi_airtime",
    "no_category_airtime",
    "no_packet_airtime",
    "noise_floor",
    "connected_clients",
    "channel_glitches",
    "bad_plcp",
    "worst_client_retry",
    "worst_client_rssi",
    "worst_client_failures",
    "router_uptime",
}
STATE_KEYS = {"reachable", "congested"}


class HomeAssistantClient:
    """Minimal read-only REST client."""

    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}

    def get(self, path: str, query: dict[str, str] | None = None) -> Any:
        """Return parsed JSON from one HA endpoint."""
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def history(
        self,
        entity_ids: list[str],
        start: datetime,
        end: datetime,
        *,
        include_attributes: bool = False,
    ) -> list[list[dict[str, Any]]]:
        """Return grouped state history for the requested entities."""
        if not entity_ids:
            return []
        query = {
            "filter_entity_id": ",".join(entity_ids),
            "end_time": end.isoformat(),
            "minimal_response": "false" if include_attributes else "true",
        }
        if not include_attributes:
            query["no_attributes"] = "true"
        encoded_start = urllib.parse.quote(start.isoformat(), safe=":+")
        return self.get(f"/api/history/period/{encoded_start}", query)


def numeric_summary(series: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return bounded summary statistics for a numeric HA history series."""
    points: list[tuple[float, str | None]] = []
    for item in series:
        try:
            value = float(item.get("state"))
        except (TypeError, ValueError):
            continue
        points.append((value, item.get("last_changed") or item.get("last_updated")))
    if not points:
        return None
    peak = max(points, key=lambda point: point[0])
    minimum = min(points, key=lambda point: point[0])
    return {
        "samples": len(points),
        "latest": points[-1][0],
        "maximum": peak[0],
        "maximum_at": peak[1],
        "minimum": minimum[0],
        "minimum_at": minimum[1],
        "average": round(sum(value for value, _ in points) / len(points), 2),
    }


def build_report(
    states: list[dict[str, Any]],
    histories: list[list[dict[str, Any]]],
    incident_histories: list[list[dict[str, Any]]],
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Organize HA states and history into a stable diagnostic report."""
    state_by_entity = {item["entity_id"]: item for item in states}
    metadata: dict[str, dict[str, Any]] = {}
    nodes: dict[str, dict[str, Any]] = {}
    health: list[dict[str, Any]] = []
    health_by_entity: dict[str, dict[str, Any]] = {}

    for entity_id, item in state_by_entity.items():
        attrs = item.get("attributes", {})
        key = attrs.get("diagnostic_key")
        if key in METRIC_KEYS or key in STATE_KEYS:
            metadata[entity_id] = {
                "key": key,
                "node_mac": attrs.get("node_mac"),
                "node_ip": attrs.get("node_ip"),
                "node_name": attrs.get("node_name"),
                "name": attrs.get("friendly_name", entity_id),
                "unit": attrs.get("unit_of_measurement"),
                "current": item.get("state"),
            }
            node_mac = attrs.get("node_mac") or "unknown"
            node_entry = nodes.setdefault(
                node_mac,
                {
                    "node_mac": node_mac,
                    "node_ip": attrs.get("node_ip"),
                    "name": attrs.get("node_name") or attrs.get("friendly_name", entity_id),
                    "current": {},
                    "history": {},
                    "state_history": {},
                },
            )
            node_entry["current"][key] = item.get("state")
            if key == "utilization":
                friendly_name = attrs.get("friendly_name", entity_id)
                node_entry["name"] = friendly_name.removesuffix(" 2.4 GHz utilization")
        name = str(attrs.get("friendly_name", "")).lower()
        if entity_id.startswith("binary_sensor.") and (
            "wan status" in name or name.endswith(" internet")
        ):
            entry = {
                "entity_id": entity_id,
                "name": attrs.get("friendly_name", entity_id),
                "current": item.get("state"),
                "history": [],
            }
            health.append(entry)
            health_by_entity[entity_id] = entry

    for series in histories:
        if not series:
            continue
        entity_id = series[0].get("entity_id")
        meta = metadata.get(entity_id)
        if entity_id in health_by_entity:
            health_by_entity[entity_id]["history"] = [
                {
                    "state": item.get("state"),
                    "at": item.get("last_changed") or item.get("last_updated"),
                }
                for item in series
            ]
        if not meta:
            continue
        if meta["key"] in STATE_KEYS:
            nodes[meta["node_mac"]]["state_history"][meta["key"]] = [
                {
                    "state": item.get("state"),
                    "at": item.get("last_changed") or item.get("last_updated"),
                }
                for item in series
            ]
            continue
        if meta["key"] not in METRIC_KEYS:
            continue
        summary = numeric_summary(series)
        if summary:
            nodes[meta["node_mac"]]["history"][meta["key"]] = {
                **summary,
                "unit": meta["unit"],
            }

    incidents = []
    for series in incident_histories:
        for item in series:
            attrs = item.get("attributes", {})
            event_type = attrs.get("event_type")
            if event_type:
                incidents.append(
                    {
                        "entity_id": item.get("entity_id"),
                        "occurred_at": item.get("state"),
                        "event_type": event_type,
                        "evidence": {
                            key: value
                            for key, value in attrs.items()
                            if key not in {"event_types", "friendly_name", "icon", "event_type"}
                        },
                    }
                )
    incidents.sort(key=lambda item: item.get("occurred_at") or "")
    return {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "nodes": sorted(nodes.values(), key=lambda item: (item["node_ip"] or "")),
        "network_health": health,
        "incidents": incidents,
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Render the compact human-facing form of a report."""
    lines = [
        "# Wi-Fi diagnostic report",
        "",
        f"Window: {report['window']['start']} through {report['window']['end']}",
        "",
    ]
    for node in report["nodes"]:
        lines.extend([f"## {node['name']}", ""])
        for key in (
            "utilization",
            "overlapping_wifi",
            "no_category_airtime",
            "no_packet_airtime",
            "worst_client_retry",
            "connected_clients",
        ):
            summary = node["history"].get(key)
            if not summary:
                continue
            unit = summary.get("unit") or ""
            lines.append(
                f"- {key}: max {summary['maximum']}{unit}, "
                f"average {summary['average']}{unit}, latest {summary['latest']}{unit}"
            )
        lines.append("")
    lines.extend(["## Incidents", ""])
    if report["incidents"]:
        for incident in report["incidents"]:
            evidence = incident["evidence"]
            lines.append(
                f"- {incident['occurred_at']}: {incident['event_type']} - "
                f"{evidence.get('node_name', incident['entity_id'])}"
            )
    else:
        lines.append("- No integration incidents were recorded in this window.")
    return "\n".join(lines)


def parse_datetime(value: str) -> datetime:
    """Parse an ISO timestamp and require timezone context."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamp must include a timezone")
    return parsed


def main() -> None:
    """Run the read-only report CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--start", type=parse_datetime)
    parser.add_argument("--end", type=parse_datetime)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args()

    end = args.end or datetime.now(UTC)
    start = args.start or end - timedelta(hours=args.hours)
    if start >= end:
        parser.error("start must be earlier than end")

    client = HomeAssistantClient(
        os.environ["HOMEASSISTANT_URL"],
        os.environ["HOMEASSISTANT_TOKEN"],
    )
    states = client.get("/api/states")
    diagnostic_ids = [
        item["entity_id"]
        for item in states
        if item.get("attributes", {}).get("diagnostic_key") in METRIC_KEYS | STATE_KEYS
    ]
    health_ids = [
        item["entity_id"]
        for item in states
        if item["entity_id"].startswith("binary_sensor.")
        and (
            "wan status" in str(item.get("attributes", {}).get("friendly_name", "")).lower()
            or str(item.get("attributes", {}).get("friendly_name", "")).lower().endswith(
                " internet"
            )
        )
    ]
    incident_ids = [
        item["entity_id"]
        for item in states
        if item["entity_id"].startswith("event.")
        and "high_utilization" in item.get("attributes", {}).get("event_types", [])
    ]
    histories = client.history(diagnostic_ids + health_ids, start, end)
    incident_histories = client.history(
        incident_ids,
        start,
        end,
        include_attributes=True,
    )
    report = build_report(states, histories, incident_histories, start, end)
    print(json.dumps(report, indent=2) if args.format == "json" else render_markdown(report))


if __name__ == "__main__":
    main()
