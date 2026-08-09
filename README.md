# ASUS Wi-Fi Diagnostics for Home Assistant

A local-polling Home Assistant custom integration for diagnosing 2.4 GHz
congestion on supported ASUSWRT/AiMesh routers. It complements the excellent
[AsusRouter](https://github.com/Vaskivskyi/ha-asusrouter) integration by exposing
radio counters that ASUSWRT does not provide through its normal client API.

## What it exposes

For each AiMesh node:

- 2.4 GHz channel utilization and a critical-congestion binary sensor
- recorder-friendly airtime components: transmit, own-network, other Wi-Fi
  (OBSS), uncategorized, and no-packet airtime
- radio noise floor, channel glitches, and malformed Wi-Fi header counts
- nearby BSSID context that separates known AiMesh radios from external Wi-Fi
  using an infrequent passive scan limited to the radio's current channel
- connected 2.4 GHz client count
- an IP-sorted client map in the connected-client sensor attributes for native
  Home Assistant dashboards
- a conservative diagnosis: normal, other Wi-Fi contention, non-Wi-Fi
  interference, client pressure, or general congestion
- the most suspicious associated client, with MAC/IP/name, signal, link rate,
  per-poll retry percentage and failure deltas as attributes
- numeric worst-client retry, signal, and failure sensors for historical correlation
- router uptime and a node reachability sensor that records partial AiMesh outages
- sparse Wi-Fi incident event entities. A sustained critical-utilization period,
  recovery, node loss/recovery, or router uptime reset stores a bounded evidence
  snapshot with the channel counters and five most suspicious clients
- an optional full-band Linux Wi-Fi probe that reports nearby external networks
  from the Home Assistant host without disconnecting its existing Wi-Fi connection

The integration uses only bounded, read-only ASUSWRT commands (`nvram get`,
`wl chanim_stats`, `wl cur_etheraddr`, `wl ssid`, a current-channel passive
`wl scan`, `wl scanresults`, `wl assoclist`, `wl sta_info`, `/proc/uptime`, and a
dnsmasq lease read).
It never changes router configuration.

Every 15 minutes, the integration passively scans only the channel the radio is
already using. It sends no probe requests and does not hop to other channels.
This is deliberately narrower and less disruptive than a site survey: it finds
the BSSIDs relevant to current-channel OBSS airtime, not every Wi-Fi network in
range.

### CouchCast full-band probe

The `collector/` directory contains a dependency-free NetworkManager probe and
systemd user timer. It runs every 15 minutes, reads the same scan results shown
by the Linux Wi-Fi panel, and reports them to the integration's LAN-only webhook.
The probe remains associated with its current network while NetworkManager scans.
Its Home Assistant URL is isolated in `~/.config/ha-wifi-probe/config`, so moving
Home Assistant only requires changing that one URL.

### Time-bounded diagnostic reports

`tools/wifi_diagnostic_report.py` reads Home Assistant's REST history without
changing any state. It groups numeric radio history by AiMesh node, includes
node reachability and existing AsusRouter WAN/Internet state transitions, and
returns the durable incident snapshots for the requested window.

```bash
HOMEASSISTANT_URL=http://homeassistant.local:8123 \
HOMEASSISTANT_TOKEN=... \
python tools/wifi_diagnostic_report.py --hours 24 --format markdown
```

Use `--start` and `--end` with timezone-aware ISO timestamps for a precise
incident window, or `--format json` for machine-readable evidence. Keep the
token in the environment rather than command history.

The incident event is deliberately sparse: high utilization must remain above
the configured critical threshold for one minute before it is recorded. Client
and nearby-network lists are bounded so Recorder does not ingest a full network
inventory every 30 seconds.

## Supported hardware

The initial release targets the tested 2.4 GHz interface layouts used by:

- ASUS ROG Rapture GT6 / GT10
- ASUS ZenWiFi XT8 / XT8 V2
- ASUS RT-AX95Q

Unknown models are skipped rather than probing arbitrary wireless interfaces.
Please open an issue with the model and safe interface mapping to add hardware.

## Installation

### HACS

1. In HACS, open **Integrations**, then the three-dot menu and **Custom
   repositories**.
2. Add `https://github.com/stavencross/ha-asus-wifi-diagnostics` as an
   **Integration** repository.
3. Download **ASUS Wi-Fi Diagnostics** and restart Home Assistant.
4. Open **Settings > Devices & services > Add integration**, search for
   **ASUS Wi-Fi Diagnostics**, and enter the AiMesh controller SSH details. If
   AsusRouter is already configured for that host, leave the credentials blank
   to reuse them without displaying or retyping the password.

SSH must be enabled on the controller and nodes, with the same username and
password. A 30-second interval is the recommended starting point. Host-key
fingerprints are learned on first contact and a later change is rejected.

### Manual

Copy `custom_components/asus_wifi_diagnostics` into Home Assistant's
`/config/custom_components` directory and restart Home Assistant.

## Portability and backups

All integration code is under `/config/custom_components` and its config entry
is part of a normal Home Assistant backup. Restoring that backup on HAOS,
Container, or another supported installation moves the integration, settings,
and entities with it. The new host must be able to reach the router IPs.

## Security notes

- Credentials are kept in the Home Assistant config entry and are redacted from
  downloadable diagnostics.
- Host-key fingerprints are recorded after the first successful connection and
  later changes are rejected. Initial enrollment is trust-on-first-use.
- Use a router account limited to LAN access where supported.

## License

MIT
