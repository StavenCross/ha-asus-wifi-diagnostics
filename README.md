# ASUS Wi-Fi Diagnostics for Home Assistant

A local-polling Home Assistant custom integration for diagnosing 2.4 GHz
congestion on supported ASUSWRT/AiMesh routers. It complements the excellent
[AsusRouter](https://github.com/Vaskivskyi/ha-asusrouter) integration by exposing
radio counters that ASUSWRT does not provide through its normal client API.

## What it exposes

For each AiMesh node:

- 2.4 GHz channel utilization and a critical-congestion binary sensor
- overlapping Wi-Fi utilization and radio noise floor
- connected 2.4 GHz client count
- a conservative diagnosis: normal, neighboring Wi-Fi, non-Wi-Fi
  interference, client pressure, or general congestion
- the most suspicious associated client, with MAC/IP/name, signal, link rate,
  per-poll retry percentage, and failures as attributes

The integration uses only bounded, read-only ASUSWRT commands (`nvram get`,
`wl chanim_stats`, `wl assoclist`, `wl sta_info`, and a dnsmasq lease read).
It never changes router configuration.

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
   **ASUS Wi-Fi Diagnostics**, and enter the AiMesh controller SSH details.

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
