#!/bin/bash
# Installé en root:root 0700 dans /usr/local/sbin/osiris-vpn-apply.sh
# Invoqué par backend/vpn.py via `sudo -n` (voir deploy/osiris-vpn.sudoers).
# N'accepte que 5 arguments positionnels — aucune interprétation shell des contenus.
# Le 4e argument ("-" si absent) est le fichier auth-user-pass (login+mdp[+totp]).
# Le 5e est la durée de la session en secondes : le tunnel se ferme seul au bout.
set -euo pipefail

SLUG="${1:?slug requis}"
OVPN_SRC="${2:?chemin config ovpn requis}"
DNSMASQ_SRC="${3:?chemin snippet dnsmasq requis}"
AUTH_SRC="${4:-"-"}"
DUREE="${5:?durée de session (secondes) requise}"

if ! [[ "$SLUG" =~ ^[a-z0-9][a-z0-9-]{0,30}$ ]]; then
    echo "slug invalide: $SLUG" >&2
    exit 1
fi

install -o root -g root -m 600 "$OVPN_SRC" "/etc/openvpn/client/${SLUG}.conf"
install -o root -g root -m 644 "$DNSMASQ_SRC" /etc/dnsmasq.d/osiris-vpn-domains.conf

if [[ "$AUTH_SRC" != "-" ]]; then
    install -o root -g root -m 600 "$AUTH_SRC" "/etc/openvpn/client/${SLUG}.auth"
else
    rm -f "/etc/openvpn/client/${SLUG}.auth"
fi

# PAS de `enable` : un tunnel ouvert en permanence garde le compte d'une personne
# connecté sur le pare-feu du client, jour et nuit (vu 2 mois et demi d'affilée).
# Il ne vit que le temps d'une session, et ne remonte pas après un redémarrage.
systemctl disable "openvpn-client@${SLUG}" 2>/dev/null || true
# restart (et non start) pour que des identifiants/TOTP mis à jour soient repris immédiatement.
systemctl restart "openvpn-client@${SLUG}"
/usr/local/sbin/osiris-vpn-session.sh "$SLUG" expire "$DUREE"
# restart et non reload : dnsmasq ne relit PAS les fichiers de /etc/dnsmasq.d/ sur SIGHUP
# (reload), donc les nouvelles lignes server=/domaine/dns et dhcp-option=121 ne seraient
# jamais prises en compte. Bref blip (~1s) DHCP/DNS/TFTP, acceptable pour une action admin.
systemctl restart dnsmasq
