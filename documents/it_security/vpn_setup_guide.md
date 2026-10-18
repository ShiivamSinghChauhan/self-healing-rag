# HelioVolt VPN Setup Guide (WireGuard + Okta)

**Doc ID:** HV-IT-003 | **Version:** 2.8 | **Updated:** Dec 20, 2025 | **Owner:** IT (it-help@heliovolt.fake)

## 1. Prerequisites
- Okta Verify enrolled (no SMS).
- OS: macOS 13+, Windows 11, Ubuntu 22.04+.
- Install WireGuard from https://www.wireguard.com/install/ + Okta Verify from App Store.

## 2. Endpoint Details
- Server: `vpn.heliovolt.fake:51820/udp`
- Internal DNS: `10.8.0.1`, `10.8.0.2`
- Allowed IPs: `10.8.0.0/16`, `172.16.50.0/24` (prod), `github.heliovolt.fake` via tunnel.
- Protocol: WireGuard, PersistentKeepalive 25 sec.

## 3. Steps (macOS example)
1. Open IT portal `it.heliovolt.fake` → Download `hv-vpn-<employeeID>.conf` (e.g., `hv-vpn-HV-0483.conf`).
2. Import into WireGuard → Activate.
3. Browser opens Okta MFA at `heliovolt.okta.fake` → Approve in Okta Verify within 60 seconds.
4. Verify: `ping 10.8.0.1` should be <40ms. Check `curl https://github.heliovolt.fake/status` returns `OK`.
5. Test DNS: `nslookup mqtt.heliovolt.fake 10.8.0.1` → `52.41.18.90`.

## 4. Troubleshooting
- **Handshake timeout:** Allow UDP 51820 outbound. Hotel Wi-Fi often blocks UDP → use phone hotspot.
- **Okta loop:** Clear cookies, use incognito, time sync must be <30s skew.
- **Slow (<5 Mbps):** Switch server to `vpn-eu.heliovolt.fake` if in Berlin.
- **Log location:** macOS `/var/log/wireguard.log`, Windows `C:\Program Files\WireGuard\log`.

## 5. Rules
- Always ON when accessing prod, GitHub Enterprise, AWS console, or on public Wi-Fi.
- Auto-disconnect after 12 hours; re-auth required.
- Never share `.conf` files. Each is bound to employee ID + YubiKey for admins.
- Contact: Slack #it-help, ext 4357, it-help@heliovolt.fake. After-hours PagerDuty for SEV1 only.

```bash
# quick test
ping -c 4 10.8.0.1
wg show
```
