# ASUS Wi-Fi Diagnostics for Home Assistant

A local-polling Home Assistant custom integration for diagnosing 2.4 and 5 GHz
congestion on supported ASUSWRT/AiMesh routers. It complements the excellent
[AsusRouter](https://github.com/Vaskivskyi/ha-asusrouter) integration by exposing
radio counters that ASUSWRT does not provide through its normal client API.

## What it exposes

For each AiMesh node:

- 2.4 GHz and client-facing 5 GHz channel utilization, each with a
  critical-congestion binary sensor
- recorder-friendly airtime components: transmit, own-network, other Wi-Fi
  (OBSS), uncategorized, and no-packet airtime
- radio noise floor, channel glitches, and malformed Wi-Fi header counts
- nearby BSSID context that separates known AiMesh radios from external Wi-Fi
  using an infrequent passive scan limited to the radio's current channel
- separate connected-client counts and client maps for 2.4 and 5 GHz
- an IP-sorted client map in the connected-client sensor attributes for native
  Home Assistant dashboards
- conservative Home Assistant ownership matching for every client. Exact MAC
  registry connections are preferred, current entity IPs are a labeled weaker
  fallback, and unmatched clients remain explicitly unmapped
- a conservative diagnosis: normal, other Wi-Fi contention, non-Wi-Fi
  interference, client pressure, or general congestion
- the most suspicious associated client, with MAC/IP/name, signal, link rate,
  per-poll retry percentage and failure deltas as attributes
- numeric worst-client retry, signal, and failure sensors for historical correlation
- a dedicated recorder-friendly presence sensor for every monitored client, publishing only
  `connected`, `not_connected`, or `unknown` plus a versioned, freshness-attributed observation;
  optional Home Assistant device ownership preserves the existing entity identity
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

### Monitored-client presence contract

Version 0.8.0 separates router observation from device or power inference. Each explicitly enrolled
MAC publishes one diagnostic enum sensor:

- `connected` means at least one eligible, current router/AP station table contains the MAC;
- `not_connected` means every eligible router/AP radio completed the current poll and none contains
  the MAC; and
- `unknown` means the observation is incomplete, stale, has no eligible observer, or an eligible AP
  failed.

The sensor attributes include contract version, poll generation, observation time, observer profile,
expected band, eligible/queried/failed observers, and the current association details when present.
A positive observation wins even if another observer fails. A missing client can never become
`not_connected` from a failed SSH command or missing radio snapshot.

These sensors are evidence providers. They do not claim that a device has mains power, infer that a
light is illuminated, or command a client. Downstream integrations may combine a fresh complete
observation with other independent evidence.

Existing v0.7 manual MAC-to-device mappings are read as monitored clients without changing their
entity unique IDs. New monitored clients may use a friendly name without linking a Home Assistant
device. Observer profiles scope completeness to `main_mesh`, `iot_ap`, or `all_client_aps`, and the
expected band may be 2.4 GHz, 5 GHz, or any.

### Standalone access points

An ASUS AP removed from AiMesh no longer appears reliably in the controller's live node inventory
and may remain there as a stale NVRAM row. Add it through **Settings > Devices & services > ASUS
Wi-Fi Diagnostics > Configure > Add a standalone access point**. The flow:

1. connects with the integration's existing SSH credentials;
2. records or verifies the AP's SSH host-key fingerprint;
3. reads only its product ID and LAN MAC;
4. rejects models without an allowlisted client-interface layout; and
5. stores the AP under one concrete observer profile.

Explicit standalone configuration overrides a stale AiMesh row for the same host so physical
client-facing interfaces are used instead of obsolete AiMesh virtual interfaces. If the optional AP
is offline during startup, main-mesh diagnostics still load and affected monitored clients remain
`unknown`. Different physical APs are collected concurrently; radios on the same AP remain
sequential to limit firmware load.

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

### Home Assistant device ownership

Each client record includes `ha_mapped`, the match method and confidence, and,
when matched, the Home Assistant device ID, name, area, integrations, and device
page URL. An unmatched named client may also include up to three ranked
`ha_suggestions` with explicit evidence. Suggestions compare device name, model,
manufacturer, mesh-node area, and integration-root relationships, but they never
become ownership until confirmed with a manual MAC mapping.

Some integrations do not expose a device MAC or IP. To add a portable manual
association, open **Settings > Devices & services > ASUS Wi-Fi Diagnostics >
Configure > Add a monitored client**. Enter the network client's MAC, name, observer
profile, and expected band. Linking a Home Assistant device is optional. Records are
stored in config-entry options and included in normal Home Assistant backups.

## Supported hardware

The integration targets the tested 2.4 GHz and client-facing 5 GHz interface
layouts used by:

- ASUS ROG Rapture GT6 / GT10
- ASUS ZenWiFi XT8 / XT8 V2
- ASUS RT-AX95Q

Unknown models are skipped rather than probing arbitrary wireless interfaces.
Please open an issue with the model and safe interface mapping to add hardware.
The dedicated 5 GHz AiMesh backhaul radio is intentionally excluded so it is
not mistaken for client traffic and does not add polling load.

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
