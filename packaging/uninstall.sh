#!/bin/sh
set -eu

ADDRESS_RULE="/rm.local/192.168.8.2"
CANONICAL_ADDRESS_RULE="/rm.lan/192.168.8.2"
LEGACY_ADDRESS_RULE="/rm.local/192.168.8.1"
LEGACY_CANONICAL_RULE="/rm-live.local/192.168.8.1"
NFT4_RULE="/rtmp.djicdn.com/4#inet#rm_live_cache#cdn_v4"
NFT6_RULE="/rtmp.djicdn.com/6#inet#rm_live_cache#cdn_v6"

[ "$(id -u)" = "0" ] || { echo "uninstall must run as root" >&2; exit 1; }

/etc/init.d/rm-live-cache stop 2>/dev/null || true
/etc/init.d/rm-live-cache disable 2>/dev/null || true
nft list table inet rm_live_cache >/dev/null 2>&1 && nft delete table inet rm_live_cache || true

rm -f /etc/nginx/conf.d/rm-live-cache.conf
nginx -t && nginx -s reload

uci -q del_list dhcp.@dnsmasq[0].address="$ADDRESS_RULE" || true
uci -q del_list dhcp.@dnsmasq[0].address="$CANONICAL_ADDRESS_RULE" || true
uci -q del_list dhcp.@dnsmasq[0].address="$LEGACY_ADDRESS_RULE" || true
uci -q del_list dhcp.@dnsmasq[0].address="$LEGACY_CANONICAL_RULE" || true
uci -q del_list dhcp.@dnsmasq[0].nftset="$NFT4_RULE" || true
uci -q del_list dhcp.@dnsmasq[0].nftset="$NFT6_RULE" || true
uci commit dhcp
rm -f /tmp/dnsmasq.d/rm-live-cache.conf

if [ -f /etc/rm-live-cache/backups/avahi-hosts-existed ]; then
    cp /etc/rm-live-cache/backups/avahi-hosts /etc/avahi/hosts
else
    sed -i '/^[[:space:]]*192\.168\.8\.1[[:space:]]\+rm\.local[[:space:]]*$/d' /etc/avahi/hosts 2>/dev/null || true
    sed -i '/^[[:space:]]*192\.168\.8\.1[[:space:]]\+rm-live\.local[[:space:]]*$/d' /etc/avahi/hosts 2>/dev/null || true
    [ -s /etc/avahi/hosts ] || rm -f /etc/avahi/hosts
fi

/etc/init.d/dnsmasq restart
/etc/init.d/avahi-daemon restart

rm -rf /tmp/rm-live-cache /www/rm-live-cache /usr/lib/rm-live-cache /etc/rm-live-cache
rm -f /etc/init.d/rm-live-cache /etc/hotplug.d/iface/95-rm-live-cache /usr/sbin/rm-live-cache-uninstall

echo "RoboMaster LAN cache completely removed."
