#!/bin/sh
set -eu

SOURCE_DIR="${1:-/tmp/rm-live-cache-install}"
ADDRESS_RULE="/rm.local/192.168.8.2"
CANONICAL_ADDRESS_RULE="/rm.lan/192.168.8.2"
LEGACY_ADDRESS_RULE="/rm.local/192.168.8.1"
LEGACY_CANONICAL_RULE="/rm-live.local/192.168.8.1"
NFT4_RULE="/rtmp.djicdn.com/4#inet#rm_live_cache#cdn_v4"
NFT6_RULE="/rtmp.djicdn.com/6#inet#rm_live_cache#cdn_v6"

[ "$(id -u)" = "0" ] || { echo "install must run as root" >&2; exit 1; }
[ -f "$SOURCE_DIR/router/usr/lib/rm-live-cache/server.py" ] || { echo "invalid source directory: $SOURCE_DIR" >&2; exit 1; }

mkdir -p /etc/rm-live-cache/backups /usr/lib/rm-live-cache /www/rm-live-cache /etc/nginx/conf.d /etc/hotplug.d/iface

if [ ! -f /etc/rm-live-cache/installed ]; then
    cp /etc/config/dhcp /etc/rm-live-cache/backups/dhcp
    if [ -f /etc/avahi/hosts ]; then
        cp /etc/avahi/hosts /etc/rm-live-cache/backups/avahi-hosts
        touch /etc/rm-live-cache/backups/avahi-hosts-existed
    fi
fi

cp "$SOURCE_DIR/router/etc/rm-live-cache/config.json" /etc/rm-live-cache/config.json
cp "$SOURCE_DIR/router/etc/rm-live-cache/firewall.nft" /etc/rm-live-cache/firewall.nft
cp "$SOURCE_DIR/router/usr/lib/rm-live-cache/server.py" /usr/lib/rm-live-cache/server.py
cp "$SOURCE_DIR/router/usr/lib/rm-live-cache/firewall.sh" /usr/lib/rm-live-cache/firewall.sh
cp "$SOURCE_DIR/router/etc/init.d/rm-live-cache" /etc/init.d/rm-live-cache
cp "$SOURCE_DIR/router/etc/hotplug.d/iface/95-rm-live-cache" /etc/hotplug.d/iface/95-rm-live-cache
cp "$SOURCE_DIR/router/etc/nginx/conf.d/rm-live-cache.conf" /etc/nginx/conf.d/rm-live-cache.conf
rm -rf /www/rm-live-cache
cp -R "$SOURCE_DIR/router/www/rm-live-cache" /www/rm-live-cache
cp "$SOURCE_DIR/rm-live-cache-extension.zip" /www/rm-live-cache/extension/rm-live-cache-extension.zip
cp "$SOURCE_DIR/packaging/uninstall.sh" /usr/sbin/rm-live-cache-uninstall
chmod 0755 /usr/lib/rm-live-cache/server.py /usr/lib/rm-live-cache/firewall.sh /etc/init.d/rm-live-cache /etc/hotplug.d/iface/95-rm-live-cache /usr/sbin/rm-live-cache-uninstall

touch /etc/rm-live-cache/installed

/etc/init.d/rm-live-cache enable
/etc/init.d/rm-live-cache restart

uci -q del_list dhcp.@dnsmasq[0].address="$ADDRESS_RULE" || true
uci -q del_list dhcp.@dnsmasq[0].address="$CANONICAL_ADDRESS_RULE" || true
uci -q del_list dhcp.@dnsmasq[0].address="$LEGACY_ADDRESS_RULE" || true
uci -q del_list dhcp.@dnsmasq[0].address="$LEGACY_CANONICAL_RULE" || true
uci -q del_list dhcp.@dnsmasq[0].nftset="$NFT4_RULE" || true
uci -q del_list dhcp.@dnsmasq[0].nftset="$NFT6_RULE" || true
uci add_list dhcp.@dnsmasq[0].address="$ADDRESS_RULE"
uci add_list dhcp.@dnsmasq[0].address="$CANONICAL_ADDRESS_RULE"
uci commit dhcp

sed -i '/^[[:space:]]*192\.168\.8\.1[[:space:]]\+rm\.local[[:space:]]*$/d' /etc/avahi/hosts 2>/dev/null || true
sed -i '/^[[:space:]]*192\.168\.8\.1[[:space:]]\+rm-live\.local[[:space:]]*$/d' /etc/avahi/hosts 2>/dev/null || true
[ -s /etc/avahi/hosts ] || rm -f /etc/avahi/hosts

/usr/lib/rm-live-cache/firewall.sh configure-dnsmasq
dnsmasq --test
nginx -t
/etc/init.d/dnsmasq restart
/etc/init.d/avahi-daemon restart
nginx -s reload

echo "RoboMaster LAN cache installed: http://rm.lan/"
echo "Uninstall with: /usr/sbin/rm-live-cache-uninstall"
