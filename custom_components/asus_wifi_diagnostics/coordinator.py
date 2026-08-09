"""Update coordinator for ASUS Wi-Fi Diagnostics."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AsusWifiDiagnosticsApi, AsusWifiDiagnosticsError
from .const import DISCOVERY_INTERVAL, DOMAIN
from .models import MeshNode, NetworkSnapshot, ProbeSnapshot
from .ownership import OwnershipIndex, build_ownership_index

_LOGGER = logging.getLogger(__name__)


class AsusWifiDiagnosticsCoordinator(DataUpdateCoordinator[NetworkSnapshot]):
    """Coordinate low-impact polling across AiMesh nodes."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: AsusWifiDiagnosticsApi,
        update_interval: timedelta,
        manual_overrides: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.api = api
        self.nodes: list[MeshNode] = []
        self._last_discovery: datetime | None = None
        self.last_node_success: dict[str, datetime] = {}
        self.webhook_id = ""
        self.manual_overrides = manual_overrides or {}
        self.ownership = OwnershipIndex({}, {}, {})

    async def _async_update_data(self) -> NetworkSnapshot:
        now = dt_util.utcnow()
        try:
            self.ownership = build_ownership_index(self.hass)
            if (
                not self.nodes
                or self._last_discovery is None
                or now - self._last_discovery >= DISCOVERY_INTERVAL
            ):
                try:
                    discovered = await self.api.discover_nodes()
                except AsusWifiDiagnosticsError:
                    if not self.nodes:
                        raise
                    _LOGGER.warning(
                        "AiMesh rediscovery failed; polling the last known node set"
                    )
                else:
                    self.nodes = discovered
                self._last_discovery = now
            snapshot = await self.api.collect(self.nodes)
            for mac in snapshot.nodes:
                self.last_node_success[mac] = now
            if self.data and self.data.probes:
                snapshot = replace(snapshot, probes=self.data.probes)
            return snapshot
        except AsusWifiDiagnosticsError as err:
            raise UpdateFailed(str(err)) from err

    @callback
    def ownership_for(self, mac: str | None, ip: str | None) -> dict:
        """Return Home Assistant ownership attributes for a router client."""
        return self.ownership.resolve(mac, ip, self.manual_overrides)

    @callback
    def snapshot_for(self, mac: str):
        """Return a node snapshot from current data."""
        return self.data.nodes.get(mac) if self.data else None

    @callback
    def failure_for(self, mac: str) -> str | None:
        """Return the bounded failure classification from the latest poll."""
        return self.data.failures.get(mac) if self.data else None

    @callback
    def async_update_probe(self, report: ProbeSnapshot) -> None:
        """Store a probe report and notify entities immediately."""
        if self.data is None:
            return
        probes = {**self.data.probes, report.probe_id: report}
        self.async_set_updated_data(replace(self.data, probes=probes))
