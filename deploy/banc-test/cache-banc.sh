#!/usr/bin/env bash
# Cache de site sur le banc : simule, sur la machine OSIRIS elle-meme, le cache
# qu'on poserait dans un site distant. Voir deploy/banc-test/README.md.
#
#   cache-banc.sh monter     espace reseau isole + dnsmasq, Caddy, Samba dedans
#   cache-banc.sh etat       ce qui tourne, et le resume des journaux
#   cache-banc.sh demonter   arrete tout et supprime l'espace reseau
#
# Le principe a prouver : sur la prise dediee, le cache porte LA MEME adresse
# qu'OSIRIS. Le PC croit parler a OSIRIS ; le cache sert lui-meme ce qui pese
# (/static, partage windows) et relaie le reste (journaux, statut, scripts)
# au vrai OSIRIS par une liaison montante.
#
#   VM de test ── tap ── pont SANS adresse ── veth ── [ espace « cache » ]
#                                                       adresse d'OSIRIS cote site
#                                                       169.254.77.2 cote montant
#   OSIRIS (hote) 169.254.77.1 ─────────── veth ───────┘
#
# Le pont n'a aucune adresse cote hote : l'hote n'apprend aucune route vers le
# reseau du site, contrairement au banc du 09/10 dont le /24 masquait un vrai
# reseau. La liaison montante est en lien-local (169.254.0.0/16), qui n'est
# jamais route : elle ne peut empieter sur rien.
set -euo pipefail

NS=${NS:-osiris-cache}
PONT=${PONT:-br-site}
TAP=${TAP:-tap-site}
MONTANT_HOTE=169.254.77.1
MONTANT_CACHE=169.254.77.2
# 1 = la VM du site sort sur Internet (miroir Ubuntu, paquets, snaps) et recoit
# un DNS public. Le cache masque la VM derriere sa liaison montante, puis l'hote
# masque le cache derriere eth0 : l'hote ne voit jamais le /24 du site, qui
# reprend l'adresse d'OSIRIS. Trois regles iptables etiquetees, retirees au
# demontage. 0 = comportement d'origine, aucune sortie.
INTERNET=${INTERNET:-0}
DNS_PUBLIC=${DNS_PUBLIC:-1.1.1.1}
SORTIE=${SORTIE:-eth0}
ETIQUETTE=banc-cache

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RACINE="$(cd "$ICI/../.." && pwd)"
TRAVAIL=${TRAVAIL:-$ICI/cache}

# Adresse d'OSIRIS telle que les scripts la gravent : c'est celle que le cache
# doit porter cote site. Lue dans la conf de l'API, jamais ecrite ici.
adresse_osiris() {
    local ip
    ip=$(grep -E '^OSIRIS_IP=' "$RACINE/backend/.env" | cut -d= -f2 | tr -d '"' || true)
    [ -n "$ip" ] || { echo "OSIRIS_IP absent de backend/.env" >&2; exit 1; }
    echo "$ip"
}

ns() { sudo ip netns exec "$NS" "$@"; }

ecrire_confs() {
    local ip=$1 prefixe=${1%.*}
    mkdir -p "$TRAVAIL"/{samba/lock,samba/state,samba/cache,samba/private,samba/pid,tftp}

    # DHCP + TFTP du site. port=0 : pas de DNS, WinPE ne travaille qu'en IP.
    cat > "$TRAVAIL/dnsmasq.conf" <<EOF
port=0
interface=veth-site
bind-interfaces
log-dhcp
dhcp-authoritative
dhcp-range=$prefixe.150,$prefixe.199,255.255.255.0,1h
dhcp-option=3,$ip
$( [ "$INTERNET" = 1 ] && echo "dhcp-option=6,$DNS_PUBLIC" )
dhcp-match=set:is_ipxe,175
dhcp-boot=tag:!is_ipxe,${FICHIER_AMORCE:-ipxe.efi},$ip
dhcp-boot=tag:is_ipxe,http://$ip/boot
enable-tftp
tftp-root=${TFTP_RACINE:-/srv/tftp}
dhcp-leasefile=$TRAVAIL/dnsmasq.leases
pid-file=$TRAVAIL/dnsmasq.pid
log-facility=$TRAVAIL/dnsmasq.log
EOF

    # Le coeur du cache : /static servi sur place, tout le reste relaye. Le Host
    # d'origine est conserve, c'est lui qui aiguille dans le Caddyfile d'OSIRIS.
    cat > "$TRAVAIL/Caddyfile" <<EOF
{
    admin off
    auto_https off
    persist_config off
}
http://:80 {
    log {
        output file $TRAVAIL/acces.log
        format console
    }
    handle_path /static/winpe-drivers/* {
        root * /srv/data/windows/winpe-drivers
        file_server
    }
    handle /static/* {
        root * $RACINE/backend
        file_server
    }
    handle {
        reverse_proxy $MONTANT_HOTE:80
    }
}
EOF

    # Partage windows en lecture seule, comme en prod. Tous les repertoires
    # d'etat sont propres au cache pour ne pas toucher au smbd de l'hote.
    cat > "$TRAVAIL/smb.conf" <<EOF
[global]
    server role = standalone server
    map to guest = Bad User
    bind interfaces only = yes
    interfaces = veth-site
    disable netbios = yes
    smb ports = 445
    lock directory = $TRAVAIL/samba/lock
    state directory = $TRAVAIL/samba/state
    cache directory = $TRAVAIL/samba/cache
    private dir = $TRAVAIL/samba/private
    pid directory = $TRAVAIL/samba/pid
    log file = $TRAVAIL/smbd.log
    log level = 1 auth:2
    logging = file
[windows]
    path = /srv/data/windows
    guest ok = yes
    read only = yes
    force user = osiris
EOF
}

monter() {
    local ip; ip=$(adresse_osiris)
    ip netns list | grep -qw "$NS" && { echo "cache deja monte : '$0 etat'"; return 0; }

    sudo ip netns add "$NS"
    ns ip link set lo up

    # Liaison montante cache -> OSIRIS
    sudo ip link add veth-cache type veth peer name veth-up
    sudo ip link set veth-up netns "$NS"
    sudo ip addr add "$MONTANT_HOTE/30" dev veth-cache
    sudo ip link set veth-cache up
    ns ip addr add "$MONTANT_CACHE/30" dev veth-up
    ns ip link set veth-up up

    # Cote site : pont sans adresse, IPv6 coupe pour qu'il reste muet
    sudo ip link add name "$PONT" type bridge
    echo 1 | sudo tee /proc/sys/net/ipv6/conf/"$PONT"/disable_ipv6 >/dev/null
    sudo ip link set "$PONT" up
    sudo ip link add veth-site-h type veth peer name veth-site
    sudo ip link set veth-site netns "$NS"
    sudo ip link set veth-site-h master "$PONT"
    sudo ip link set veth-site-h up
    ns ip addr add "$ip/24" dev veth-site
    ns ip link set veth-site up
    sudo ip tuntap add dev "$TAP" mode tap user "$USER"
    sudo ip link set "$TAP" master "$PONT"
    sudo ip link set "$TAP" up

    if [ "$INTERNET" = 1 ]; then ouvrir_internet; fi

    ecrire_confs "$ip"
    ns /usr/sbin/dnsmasq --conf-file="$TRAVAIL/dnsmasq.conf"
    ns /usr/sbin/smbd -D -s "$TRAVAIL/smb.conf"
    ns caddy start --config "$TRAVAIL/Caddyfile" --adapter caddyfile --pidfile "$TRAVAIL/caddy.pid" >/dev/null 2>&1

    echo "cache monte : $ip cote site (pont $PONT, interface $TAP), $MONTANT_CACHE vers OSIRIS"
    echo "VM : PONT=$PONT TAP=$TAP PXE=1 ./banc-test.sh demarrer"
}

# Regles hote : uniquement ce qui vient du cache, et son retour.
regles_hote() {
    local action=$1 c=(-m comment --comment "$ETIQUETTE")
    sudo iptables "$action" FORWARD -i veth-cache -o "$SORTIE" "${c[@]}" -j ACCEPT
    sudo iptables "$action" FORWARD -i "$SORTIE" -o veth-cache -m conntrack --ctstate RELATED,ESTABLISHED "${c[@]}" -j ACCEPT
    sudo iptables -t nat "$action" POSTROUTING -s "$MONTANT_CACHE/32" -o "$SORTIE" "${c[@]}" -j MASQUERADE
}

ouvrir_internet() {
    ns sysctl -qw net.ipv4.ip_forward=1
    ns ip route add default via "$MONTANT_HOTE"
    ns iptables -t nat -A POSTROUTING -o veth-up -j MASQUERADE
    regles_hote -I
    echo "internet : ouvert (DNS $DNS_PUBLIC, sortie $SORTIE)"
}

fermer_internet() {
    # Chaque regle est retiree tant qu'elle existe : un demontage relance ne
    # doit pas echouer, ni laisser une regle en double.
    while sudo iptables -S FORWARD | grep -q -- "--comment $ETIQUETTE"; do
        regles_hote -D 2>/dev/null || break
    done
}

etat() {
    ip netns list | grep -qw "$NS" || { echo "cache : non monte"; return 0; }
    echo "cache   : monte (espace $NS)"
    for p in dnsmasq smbd caddy; do
        local f="$TRAVAIL/$p.pid"; [ "$p" = smbd ] && f="$TRAVAIL/samba/pid/smbd.pid"
        if sudo test -f "$f" && sudo kill -0 "$(sudo cat "$f")" 2>/dev/null; then echo "  $p : actif"; else echo "  $p : ARRETE"; fi
    done
    if sudo iptables -S FORWARD | grep -q -- "--comment $ETIQUETTE"; then echo "internet: ouvert"; else echo "internet: ferme"; fi
    echo "baux    : $(sudo cat "$TRAVAIL/dnsmasq.leases" 2>/dev/null | wc -l)"
    if sudo test -f "$TRAVAIL/acces.log"; then
        echo "servi sur place : $(sudo grep -c '/static/' "$TRAVAIL/acces.log" || true) requetes"
        echo "relaye a OSIRIS : $(sudo grep -vc '/static/' "$TRAVAIL/acces.log" || true) requetes"
    fi
}

demonter() {
    local f
    for f in "$TRAVAIL/dnsmasq.pid" "$TRAVAIL/caddy.pid" "$TRAVAIL/samba/pid/smbd.pid"; do
        sudo test -f "$f" && sudo kill "$(sudo cat "$f")" 2>/dev/null || true
    done
    fermer_internet
    sudo ip link del "$TAP" 2>/dev/null || true
    sudo ip link del veth-site-h 2>/dev/null || true
    sudo ip link del "$PONT" 2>/dev/null || true
    sudo ip link del veth-cache 2>/dev/null || true
    sudo ip netns del "$NS" 2>/dev/null || true
    echo "cache demonte (journaux gardes dans $TRAVAIL)"
}

case "${1:-}" in
    monter)   monter ;;
    etat)     etat ;;
    demonter) demonter ;;
    *) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//' ; exit 1 ;;
esac
