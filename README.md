# RoboMaster LAN Live Cache

This project deploys a removable RoboMaster 720p main-stream cache to a
GL.iNet Slate 7. It uses the router's existing NGINX for LAN delivery and the
preinstalled Python runtime for HLS source discovery and segment coordination.

## Installed endpoints

- `http://rm.lan/` – canonical clean local player
- `http://rm.local/` – requested compatibility alias when no mDNS collision exists
- `http://192.168.8.2/` – private-IP fallback and extension transport
- `http://rm.lan/live.m3u8` – current 720p main HLS entry
- `http://rm.lan/api/status` – cache statistics
- `http://rm.lan/extension/` – Chrome/Edge extension and instructions

On this router, official RoboMaster web/CDN addresses that fail on the direct
LAN forwarding path are narrowly redirected through the already-running
OpenClash transparent listener. The video CDN block remains earlier in the
packet path, so clients still cannot bypass the local cache.

## Router lifecycle

```sh
/etc/init.d/rm-live-cache status
/etc/init.d/rm-live-cache restart
/usr/sbin/rm-live-cache-uninstall
```

The uninstall command removes the service, NGINX virtual host, DNS entries,
DNS aliases/drop-in, firewall table, web files, extension, and temporary cache. It does
not remove or replace any GL.iNet packages.
