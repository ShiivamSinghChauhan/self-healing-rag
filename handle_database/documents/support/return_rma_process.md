# HelioVolt RMA & Returns Process (Internal + Customer)

**Doc ID:** HV-SUP-003 | **Version:** 3.3 | **Updated:** Jan 20, 2026

## 1. Eligibility Check (L1 does this)
1. Verify serial format: EP-2024/2025-XXXXXX, VG-X5-XXXXXX, LS2-XXXXXX.
2. Verify invoice date in NetSuiteFake. Warranty = 3 years from invoice. Returns = 30 days if unopened.
3. Ask for: photo of wiring, firmware version (must be on latest: EcoPulse 2.3.7, VoltGrid 1.9.2, LumenSense 3.1.4), troubleshooting steps tried (see troubleshooting_faq.txt).

## 2. Create RMA
- Portal: support.heliovolt.fake → New RMA. Prefix: `RMA-2026-XXXX` (e.g., RMA-2026-1047).
- Reason codes: DEFECT, DOA (dead on arrival <7 days), SHIPPING_DAMAGE, WRONG_ITEM, FIRMWARE_BRICK.
- DOA ships free both ways + replacement in 2 business days regardless of SLA.

## 3. Shipping
- Customer ships to: RMA Depot, 4400 Helios Way Bldg B, Austin TX 78758.
- Prepaid label via ShippoFake for DEFECT/DOA within warranty. Customer pays for out-of-warranty.
- Standard turnaround: replacement ships 5 business days after depot receives unit.
- Advanced Replacement (Professional/Enterprise only): ships in 2 business days with card hold for MSRP ($189 / $1249 / $59). Must receive defective in 14 days or charge holds.

## 4. Refund Formula (if replacement declined and >12 months)
`refund = purchase_price * (36 - months_used)/36`. Example in warranty_policy.txt: $189 at month 18 → $94.50.

## 5. Restocking (non-warranty returns)
Unopened <30 days: full refund. Opened-unused <30 days: 15% fee. No returns >30 days.

## 6. Contacts & SLA
support@heliovolt.fake | +1-512-555-0147 Mon-Fri 8am-6pm CT. First response: Standard 24h (business), Premium 4h, Enterprise 1h 24/7. Status tracked in ZendeskFake.

> Example RMA: RMA-2026-1047 for VG-X5-008812 (Acme Logistics) — CT clamp fault, Advanced Replacement shipped Jan 22, 2026.
