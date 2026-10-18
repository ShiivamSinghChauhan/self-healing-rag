# Meeting Notes — Q2 2026 Planning (Internal)

**Date:** March 18, 2026, 10:00 AM – 12:00 PM CT | **Location:** Austin HQ Rm 3A + Zoom | **Attendees:** Maya Rangan (CEO), Daniel Okoro (CTO), Priya Desai (CFO), Sofia Marchetti (HR), James Park (CISO) | **Doc ID:** HV-OPS-020

## 1. Headcount & Hiring
- Current 482 staff. Approved to hire +38 in Q2 (Engineering 20, Support 8, Sales 10). Freeze on Berlin hiring until work-permit backlog cleared (5 pending).
- Offer approval threshold: Manager up to $120k, VP up to $180k, CEO above $180k.

## 2. Product Milestones
- EcoPulse v2.4 firmware (adds Matter support) slips to June 15, 2026 due to Thread radio bug TR-882. Beta serials EP-2026-BETA-xxx.
- VoltGrid X500 UL certification passed March 10, 2026 (File E551234). Production ramp to 5,000 units/month in May.
- Cloud v4.2 adds demand-response API `POST /v4/demand-response/events`. Launch May 1, 2026. EU shard migration to eu-central-1b complete March 12.

## 3. Sales & Finance
- Q1 2026 revenue $4.82M (target $4.5M, +7.1%). Best seller: VoltGrid X500 (1,840 units).
- Q2 target $5.4M. Pricing freeze until July. Discount >20% needs CFO approval.
- Top customer: Acme Logistics (org slug acme-hq-042) — 420 thermostats, $310k ARR.

## 4. Security & Compliance
- SOC 2 Type II audit window June 1-30, 2026 (auditor: SensibaFake). No prod deploys on Fridays during audit.
- Pen test finding PT-44 (MQTT auth bypass on firmware <2.3.5) must be patched by April 30. CISO owns.

## 5. Action Items
- [ ] Daniel: Publish TR-882 postmortem by Mar 25 → eng wiki.
- [ ] Priya: Update pricing_tiers.json with 2026 enterprise overage $0.12/k-device-msg.
- [ ] Sofia: Roll out 2026 holiday calendar (12 days) + Summer Fridays pilot (half-day Fri in July).
- [ ] James: Rotate all `hv_prod_*` AWS keys by Apr 5.

Next meeting: April 22, 2026.
