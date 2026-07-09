#!/bin/bash
# Installé en root:root 0700 dans /usr/local/sbin/osiris-vpn-disable.sh
# Invoqué par backend/vpn.py via `sudo -n` (voir deploy/osiris-vpn.sudoers).
set -euo pipefail

SLUG="${1:?slug requis}"
DNSMASQ_SRC="${2:?chemin snippet dnsmasq requis}"

if ! [[ "$SLUG" =~ ^[a-z0-9][a-z0-9-]{0,30}$ ]]; then
    echo "slug invalide: $SLUG" >&2
    exit 1
fi

systemctl disable --now "openvpn-client@${SLUG}" 2>/dev/null || true
rm -f "/etc/openvpn/client/${SLUG}.conf" "/etc/openvpn/client/${SLUG}.auth"
install -o root -g root -m 644 "$DNSMASQ_SRC" /etc/dnsmasq.d/osiris-vpn-domains.conf
# restart et non reload : dnsmasq ne relit pas /etc/dnsmasq.d/ sur SIGHUP (voir apply).
systemctl restart dnsmasq
