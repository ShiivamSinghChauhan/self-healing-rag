# HelioVolt Cloud Platform API Guide v4.1

**Doc ID:** HV-PROD-010 | **Version:** 4.1.2 | **Updated:** Jan 28, 2026 | **Base URLs:** US `https://api.heliovolt.fake/v4`, EU `https://api-eu.heliovolt.fake/v4`

## Auth
All calls need `Authorization: Bearer <API_KEY>`. Get key from Dashboard → Settings → API Keys. Keys rotate every 90 days. Format: `hv_live_...` (51 chars). Rate limit: 600 req/min per org (Starter 100/min). EU data stays in `eu-central-1`.

```bash
curl -H "Authorization: Bearer hv_live_abc123EXAMPLEkey00000000000000000001" \
  https://api.heliovolt.fake/v4/devices
```

## Core Endpoints

### List Devices
`GET /devices?type=ecopulse&limit=50`
Response includes `serial` (e.g., `EP-2025-001234`), `firmware` (e.g., `2.3.7`), `last_seen`.

### Telemetry
`GET /devices/{serial}/telemetry?from=2026-01-01&to=2026-01-31&metric=watts`
Metrics: `watts`, `kwh_today`, `temp_c`, `humidity`, `lux`, `occupancy`. Max range 31 days. Data retention 13 months rolling.

Example response:
```json
{"serial":"VG-X5-008812","watts":3420,"kwh_today":28.4,"timestamp":"2026-01-15T14:00:00Z"}
```

### Set Thermostat
`POST /devices/{serial}/setpoint` body `{"heat_c":21.5,"cool_c":24.0,"mode":"auto"}`
Range heat 10-26°C, cool 18-30°C. Requires `devices:write` scope.

### Provision VoltGrid
`POST /provision` body `{"serial":"VG-X5-008812","org_slug":"acme-hq-042","pin":"48291037"}` — PIN is 8-digit on side label.

## Webhooks
Register at Dashboard → Webhooks. Events: `device.offline`, `alert.high_usage`, `rma.updated`. Secret header `X-HV-Signature` HMAC-SHA256. Retry 5x exponential backoff.

## Error Codes
- `ORG_NOT_FOUND (404)` — wrong shard; try `api-eu.heliovolt.fake` for EU orgs.
- `RATE_LIMIT (429)` — backoff 60 sec, header `Retry-After`.
- `INVALID_SETPOINT (422)` — out of range.
- Support: developers@heliovolt.fake | docs at `docs.heliovolt.fake`.

## SDKs
Python `pip install heliovolt==4.1.0`, Node `npm i @heliovolt/sdk@4.1`. Example Python:
```python
from heliovolt import Client
c = Client(api_key="hv_live_...")
c.set_setpoint("EP-2025-001234", heat_c=21.5, cool_c=24.0)
```
