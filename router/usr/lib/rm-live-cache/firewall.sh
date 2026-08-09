#!/bin/sh

TABLE="inet rm_live_cache"
HOST="rtmp.djicdn.com"
OFFICIAL_HOSTS="www.robomaster.com robomaster.com rm-static.djicdn.com assets.djicdn.com leancloud.robomaster.com saas.robomaster.com app-router.leancloud.cn router-g0-push.leancloud.cn"
DNSMASQ_DROPIN="/tmp/dnsmasq.d/rm-live-cache.conf"

configure_dnsmasq() {
    mkdir -p "$(dirname "$DNSMASQ_DROPIN")"
    {
        echo "nftset=/$HOST/4#inet#rm_live_cache#cdn_v4"
        echo "nftset=/$HOST/6#inet#rm_live_cache#cdn_v6"
    } >"$DNSMASQ_DROPIN"
}

create_table() {
    nft list table $TABLE >/dev/null 2>&1 && nft delete table $TABLE
    nft -f /etc/rm-live-cache/firewall.nft
}

add_ip() {
    case "$1" in
        *:*) nft add element $TABLE cdn_v6 "{ $1 }" >/dev/null 2>&1 || true ;;
        *.*) nft add element $TABLE cdn_v4 "{ $1 }" >/dev/null 2>&1 || true ;;
    esac
}

add_official_ip() {
    case "$1" in
        *.*) nft add element $TABLE official_v4 "{ $1 }" >/dev/null 2>&1 || true ;;
    esac
}

refresh_official() {
    # Port 7892 is OpenClash's transparent TCP listener on this router. Leave
    # the set empty when it is unavailable so official traffic remains direct.
    netstat -lnt 2>/dev/null | grep -q ':7892 ' || return 0
    for pass in 1 2; do
        for official_host in $OFFICIAL_HOSTS; do
            nslookup "$official_host" 127.0.0.1 2>/dev/null |
                awk '/^Address: / { print $2 }' |
                while IFS= read -r address; do
                    [ -n "$address" ] && add_official_ip "$address"
                done
        done
    done
}

refresh() {
    nft list table $TABLE >/dev/null 2>&1 || create_table
    # CDN DNS rotates addresses. Sample several responses at startup/refresh so
    # clients with an already cached address are covered too. dnsmasq adds any
    # later answers to the same nft sets through the drop-in above.
    for pass in 1 2 3 4; do
        for resolver in 127.0.0.1 223.5.5.5 119.29.29.29; do
            nslookup "$HOST" "$resolver" 2>/dev/null |
                awk '/^Address: / { print $2 }' |
                while IFS= read -r address; do
                    [ -n "$address" ] && add_ip "$address"
                done
        done
    done
    refresh_official
}

destroy() {
    nft list table $TABLE >/dev/null 2>&1 && nft delete table $TABLE
}

case "$1" in
    configure-dnsmasq) configure_dnsmasq ;;
    create) create_table ;;
    refresh) refresh ;;
    destroy) destroy ;;
    run)
        while true; do
            refresh
            sleep 60
        done
        ;;
    *) echo "usage: $0 {configure-dnsmasq|create|refresh|destroy|run}" >&2; exit 2 ;;
esac
