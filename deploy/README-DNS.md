# LAN-wide DNS: smarttradeai.local → this machine

Goal: any device on your LAN can browse to `http://smarttradeai.local/`
instead of `http://192.168.29.228/`.

This machine's current LAN IP: **192.168.29.228** (Wi-Fi). Two things to do
regardless of which path below you use:

1. **Reserve that IP in your router's DHCP settings** (usually called
   "Address Reservation" / "DHCP Reservation" / "Static Lease" — look for
   this machine's device name or MAC address in the router's connected-
   devices list). Without this, the IP can change on reboot and the mapping
   below goes stale.
2. Pick one path:

## Path A — your router supports custom DNS entries (try this first)

Log into your router's admin page and look for a section named something
like **"Local DNS" / "Static DNS Assignment" / "Host Records" / "DNS
Overrides"** (naming varies a lot by brand — TP-Link, Asus, Netgear, and
UniFi/pfSense/OPNsense-based routers all use different names for this, and
plenty of budget routers don't have it at all).

If you find it: add an entry mapping `smarttradeai.local` → `192.168.29.228`,
save/apply, and you're done — no software needed on this machine.

## Path B — router doesn't support it: local DNS server on this machine

1. Install **Acrylic DNS Proxy** (free, open source) from one of:
   - https://sourceforge.net/projects/acrylic/ (primary official repo)
   - https://mayakron.altervista.org/ (developer's homepage)
2. After installing, open (as admin) the config file it created at
   `C:\Program Files (x86)\Acrylic DNS Proxy\AcrylicHosts.txt` and add the
   line from `deploy/dns/AcrylicHosts.txt` in this repo:
   ```
   192.168.29.228   smarttradeai.local
   ```
3. Restart the service so it picks up the change:
   ```powershell
   Restart-Service AcrylicDNSProxySvc
   ```
4. Test from this machine first: `nslookup smarttradeai.local 127.0.0.1`
   should return `192.168.29.228`.
5. Now make OTHER devices use this machine as their DNS server. The clean
   way (no per-device setup): in your router's WAN/Internet or DHCP
   settings, change **"DNS Server"** from Auto/ISP to `192.168.29.228`.
   Acrylic forwards every non-`.local` query upstream, so normal internet
   browsing for everyone on the network keeps working unchanged.

   (Alternative if you don't want to touch the router: manually set DNS to
   `192.168.29.228` in each individual device's network settings instead —
   works, but you'd repeat it per device.)

## Verifying it all works

From any device on the LAN, once DNS resolves: `http://smarttradeai.local/`
should load the SmartTradeAI login page — same site as
`http://192.168.29.228/`, just reachable by name. Requires the IIS reverse
proxy from `deploy/README.md` to already be set up (this DNS step only
solves *naming*, not the proxy itself).
