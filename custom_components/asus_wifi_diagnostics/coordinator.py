"""Update coordinator for ASUS Wi-Fi Diagnostics."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AsusWifiDiagnosticsApi, AsusWifiDiagnosticsError
from .const import DISCOVERY_INTERVAL, DOMAIN
from .models import MeshNode, NetworkSnapshot


class AsusWifiDiagnosticsCoordinator(DataUpdateCoordinator[NetworkSnapshot]):
    """Coordinate low-impact polling across AiMesh nodes."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: AsusWifiDiagnosticsApi,
        update_interval: timedelta,
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

    async def _async_update_data(self) -> NetworkSnapshot:
        now = dt_util.utcnow()
        try:
            if (
                not self.nodes
                or self._last_discovery is None
                or now - self._last_discovery >= DISCOVERY_INTERVAL
            ):
                self.nodes = await self.api.discover_nodes()
                self._last_discovery = now
            return await self.api.collect(self.nodes)
        except AsusWifiDiagnosticsError as err:
            raise UpdateFailed(str(err)) from err

    @callback
    def snapshot_for(self, mac: str):
        """Return a node snapshot from current data."""
        return self.data.nodes.get(mac) if self.data else None

