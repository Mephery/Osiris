#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
#
# Installe un cache de site OSIRIS sur un Debian ou Ubuntu neuf. Voir README.md.
#
#   installer-cache.sh installer --manager <adresse> --osiris-ip <ip> \
#                                --carte-site <interface> [options]
#   installer-cache.sh verifier       controle chaque piece et dit ce qui ne va pas
#
# Options d'installation :
#   --carte-lien <if>     carte vers le manager (defaut : celle de la route par defaut)
#   --dns <ip,ip>         DNS donnes aux PC (defaut : ceux du cache) - il faut ceux
#                         du domaine pour la jonction AD
#   --debit-max <Ko/s>    plafond de la copie de nuit (defaut 0 = sans limite)
#   --fenetre <hh:mm-hh:mm>  fenetre de la copie de nuit (defaut 01:00-05:00)
#   --empreinte <SHA256:...> empreinte SSH attendue du manager (sinon demandee)
#   --jeton <jeton>       jeton du site (sinon demande sans etre affiche)
#
# Le script peut etre relance : il remplace sa propre configuration, rien d'autre.
set -euo pipefail

RACINE=/srv/osiris-cache
ETC=/etc/osiris-cache
OPT=/opt/osiris-cache
ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

rouge()  { printf '\033[31m%s\033[0m\n' "$*"; }
vert()   { printf '\033[32m%s\033[0m\n' "$*"; }
etape()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
refus()  { rouge "REFUS : $*" >&2; exit 1; }

# ── Lecture des options ─────────────────────────────────────────────────────

MANAGER="" OSIRIS_IP="" JETON="" CARTE_SITE="" CARTE_LIEN="" DNS=""
DEBIT_MAX_KO=0 FENETRE="01:00-05:00" EMPREINTE=""

lire_options() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --manager)    MANAGER=$2; shift 2 ;;
            --osiris-ip)  OSIRIS_IP=$2; shift 2 ;;
            --jeton)      JETON=$2; shift 2 ;;
            --carte-site) CARTE_SITE=$2; shift 2 ;;
            --carte-lien) CARTE_LIEN=$2; shift 2 ;;
            --dns)        DNS=$2; shift 2 ;;
            --debit-max)  DEBIT_MAX_KO=$2; shift 2 ;;
            --fenetre)    FENETRE=$2; shift 2 ;;
            --empreinte)  EMPREINTE=$2; shift 2 ;;
            *) refus "option inconnue : $1" ;;
        esac
    done
    [ -n "$MANAGER" ]    || refus "--manager manquant (adresse d'OSIRIS joignable depuis ce cache)"
    [ -n "$OSIRIS_IP" ]  || refus "--osiris-ip manquant (OSIRIS_IP du manager, celle que les PC connaissent)"
    if [ -z "$JETON" ]; then
        # Demande sans echo : passe en option, il resterait dans l'historique du shell
        # et visible dans la liste des processus le temps de l'installation.
        read -r -s -p "Jeton du site (affiche une fois a sa creation dans OSIRIS) : " JETON; echo
    fi
    [ -n "$JETON" ]      || refus "jeton du site manquant"
    [ -n "$CARTE_SITE" ] || refus "--carte-site manquant (la carte reliee a la prise d'installation)"
    [[ "$OSIRIS_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || refus "--osiris-ip n'est pas une adresse IPv4 : $OSIRIS_IP"
    [[ "$FENETRE" =~ ^[0-2][0-9]:[0-5][0-9]-[0-2][0-9]:[0-5][0-9]$ ]] || refus "--fenetre attendue sous la forme 01:00-05:00"
    [[ "$DEBIT_MAX_KO" =~ ^[0-9]+$ ]] || refus "--debit-max attend un nombre de Ko/s"
    if [ -z "$CARTE_LIEN" ]; then
        CARTE_LIEN=$(ip -4 route show default | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')
    fi
    [ -n "$CARTE_LIEN" ] || refus "aucune route par defaut : preciser --carte-lien"
    [ "$CARTE_LIEN" != "$CARTE_SITE" ] || refus "la carte site et la carte lien sont la meme ($CARTE_SITE) : il faut deux cartes"
    if [ -z "$DNS" ]; then
        DNS=$(awk '/^nameserver/ && $2 !~ /^127\./ {print $2}' /etc/resolv.conf | paste -sd, -)
    fi
}

# Plage DHCP de la prise : dans le /24 d'OSIRIS_IP, sans jamais la contenir.
plage_dhcp() {
    local base=${OSIRIS_IP%.*} dernier=${OSIRIS_IP##*.}
    if [ "$dernier" -lt 100 ] || [ "$dernier" -gt 199 ]; then
        echo "$base.100,$base.199"
    else
        echo "$base.20,$base.99"
    fi
}

# ── Garde-fou : la carte site doit etre sur un reseau a part ────────────────
# Sur la prise d'installation, le cache prend l'adresse d'OSIRIS et distribue des
# adresses. Branchee par erreur sur un reseau en service, la carte creerait un
# doublon de l'adresse d'OSIRIS et un second DHCP : les deploiements et les postes
# de ce reseau tomberaient. On regarde donc, AVANT de rien activer, si quelqu'un y
# repond deja.
garde_fou_carte_site() {
    ip link show "$CARTE_SITE" >/dev/null 2>&1 || refus "carte $CARTE_SITE introuvable (ip -br link)"
    ip link set "$CARTE_SITE" up
    # Deja configuree par nous : la verification a deja ete faite a la premiere installation.
    if ip -4 addr show "$CARTE_SITE" | grep -q " $OSIRIS_IP/"; then
        echo "carte $CARTE_SITE deja configuree par une installation precedente"
        return
    fi
    local essais=0
    until ip link show "$CARTE_SITE" | grep -q 'LOWER_UP'; do
        essais=$((essais + 1))
        [ $essais -ge 10 ] && refus "aucun cable sur $CARTE_SITE. Brancher la carte site sur la prise d'installation (ou directement sur un PC), puis relancer."
        sleep 1
    done
    echo "recherche d'un serveur DHCP deja present sur $CARTE_SITE..."
    if busybox udhcpc -i "$CARTE_SITE" -n -q -t 3 -T 2 -s /bin/true >/dev/null 2>&1; then
        refus "un serveur DHCP repond deja sur $CARTE_SITE. Cette carte est sur un reseau en service, pas sur une prise isolee : le cache y casserait les adresses des postes. Brancher $CARTE_SITE sur la prise dediee (ou en direct sur le PC a installer)."
    fi
    echo "recherche d'une machine portant deja $OSIRIS_IP sur $CARTE_SITE..."
    if ! arping -D -q -I "$CARTE_SITE" -c 3 "$OSIRIS_IP"; then
        refus "une machine repond deja a $OSIRIS_IP sur $CARTE_SITE (probablement OSIRIS lui-meme). La carte site est branchee sur le reseau d'OSIRIS : le cache creerait un doublon de son adresse."
    fi
    vert "carte $CARTE_SITE : reseau isole, ni DHCP ni $OSIRIS_IP en face"
}

# ── Configuration ───────────────────────────────────────────────────────────

configurer_carte_site() {
    # L'adresse doit survivre au redemarrage. Deux cas courants :
    # - systemd-networkd (Ubuntu serveur, images cloud Debian, souvent sous netplan) :
    #   on ecrit un fichier .network DIRECT, prefixe 05. Passer par netplan ne suffit
    #   pas : cloud-init y declare souvent deja la carte (50-cloud-init.yaml), et
    #   entre deux declarations c'est la premiere par ordre alphabetique qui gagne,
    #   la sienne. L'adresse d'OSIRIS ne serait jamais posee.
    # - ifupdown (Debian installe classiquement) : /etc/network/interfaces.d.
    if systemctl is-active -q systemd-networkd; then
        cat > /etc/systemd/network/05-osiris-site.network <<EOF
# Carte de la prise d'installation : porte l'adresse d'OSIRIS (osiris-cache).
# Prefixe 05 : passe avant les fichiers de netplan et cloud-init (10-netplan-*).
[Match]
Name=$CARTE_SITE

[Link]
RequiredForOnline=no

[Network]
Address=$OSIRIS_IP/24
DHCP=no
LinkLocalAddressing=no
IPv6AcceptRA=no
ConfigureWithoutCarrier=yes
EOF
        networkctl reload
        networkctl reconfigure "$CARTE_SITE"
    elif [ -f /etc/network/interfaces ]; then
        grep -q '^source /etc/network/interfaces.d/\*' /etc/network/interfaces 2>/dev/null \
            || echo 'source /etc/network/interfaces.d/*' >> /etc/network/interfaces
        install -d /etc/network/interfaces.d
        cat > /etc/network/interfaces.d/osiris-site <<EOF
# Carte de la prise d'installation : porte l'adresse d'OSIRIS (osiris-cache)
auto $CARTE_SITE
iface $CARTE_SITE inet static
    address $OSIRIS_IP/24
EOF
        ip -4 addr show "$CARTE_SITE" | grep -q " $OSIRIS_IP/" || ip addr add "$OSIRIS_IP/24" dev "$CARTE_SITE"
    else
        refus "ni systemd-networkd ni ifupdown : poser a la main $OSIRIS_IP/24 sur $CARTE_SITE, puis relancer"
    fi
    local essais=0
    until ip -4 addr show "$CARTE_SITE" | grep -q " $OSIRIS_IP/"; do
        essais=$((essais + 1))
        [ $essais -ge 10 ] && refus "$OSIRIS_IP n'a pas pu etre posee sur $CARTE_SITE (voir networkctl status $CARTE_SITE)"
        sleep 1
    done
    # Pas d'IPv6 sur la prise : rien ne s'en sert, et elle n'a pas a se signaler.
    echo "net.ipv6.conf.$CARTE_SITE.disable_ipv6 = 1" > /etc/sysctl.d/60-osiris-cache.conf
    # Les PC sortent par le cache (jonction au domaine, Windows Update, winget).
    echo "net.ipv4.ip_forward = 1" >> /etc/sysctl.d/60-osiris-cache.conf
    sysctl -q -p /etc/sysctl.d/60-osiris-cache.conf
}

configurer_dhcp() {
    local dns_opt=""
    [ -n "$DNS" ] && dns_opt="dhcp-option=6,$DNS"
    cat > /etc/dnsmasq.d/osiris-cache.conf <<EOF
# Cache OSIRIS : DHCP et TFTP de la prise d'installation, et RIEN ailleurs.
# port=0 : pas de DNS ; les PC recoivent ceux du site ci-dessous.
port=0
interface=$CARTE_SITE
bind-interfaces
log-dhcp
dhcp-authoritative
dhcp-range=$(plage_dhcp),255.255.255.0,2h
dhcp-option=3,$OSIRIS_IP
$dns_opt
dhcp-match=set:is_ipxe,175
dhcp-boot=tag:!is_ipxe,ipxe.efi,$OSIRIS_IP
dhcp-boot=tag:is_ipxe,http://$OSIRIS_IP/boot
enable-tftp
tftp-root=$RACINE/tftp
EOF
    systemctl enable dnsmasq >/dev/null 2>&1
    systemctl restart dnsmasq
}

configurer_relais() {
    [ -f /etc/caddy/Caddyfile ] && [ ! -f /etc/caddy/Caddyfile.avant-osiris ] \
        && cp -p /etc/caddy/Caddyfile /etc/caddy/Caddyfile.avant-osiris
    cat > /etc/caddy/Caddyfile <<EOF
# Cache OSIRIS : ce qui pese est servi ici, le reste est relaye au manager.
# Le nom d'hote demande par le PC (l'adresse d'OSIRIS) est transmis tel quel :
# c'est lui qui aiguille la requete dans le Caddyfile du manager.
{
    auto_https off
}
http://$OSIRIS_IP:80 {
    bind $OSIRIS_IP 127.0.0.1
    log {
        output file /var/log/caddy/osiris-cache.log
        format console
    }
    handle_path /static/winpe-drivers/* {
        root * $RACINE/windows/winpe-drivers
        file_server
    }
    handle_path /static/* {
        root * $RACINE/static
        file_server
    }
    handle {
        reverse_proxy http://$MANAGER:80
    }
}
EOF
    mkdir -p /var/log/caddy && chown caddy:caddy /var/log/caddy 2>/dev/null || true
    systemctl enable caddy >/dev/null 2>&1
    systemctl restart caddy
}

configurer_partage() {
    [ -f /etc/samba/smb.conf ] && [ ! -f /etc/samba/smb.conf.avant-osiris ] \
        && cp -p /etc/samba/smb.conf /etc/samba/smb.conf.avant-osiris
    cat > /etc/samba/smb.conf <<EOF
# Cache OSIRIS : le partage des images, en lecture seule, sur la prise seulement.
[global]
    server role = standalone server
    map to guest = Bad User
    interfaces = $CARTE_SITE
    bind interfaces only = yes
    disable netbios = yes
    smb ports = 445
    log file = /var/log/samba/log.%m
    max log size = 1000

[windows]
    path = $RACINE/windows
    guest ok = yes
    read only = yes
EOF
    systemctl enable smbd >/dev/null 2>&1
    systemctl restart smbd
    systemctl disable --now nmbd >/dev/null 2>&1 || true
}

# NAT des PC de la prise vers le reseau du site. Table a part : on ne touche pas
# au pare-feu existant de la machine.
configurer_nat() {
    cat > "$ETC/nat.nft" <<EOF
table ip osiris_cache
delete table ip osiris_cache
table ip osiris_cache {
    chain forward {
        type filter hook forward priority 0; policy accept;
    }
    chain postrouting {
        type nat hook postrouting priority 100; policy accept;
        iifname "$CARTE_SITE" oifname "$CARTE_LIEN" masquerade
    }
}
EOF
    cat > /etc/systemd/system/osiris-cache-nat.service <<EOF
[Unit]
Description=NAT des PC de la prise d'installation (cache OSIRIS)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f $ETC/nat.nft
ExecStop=/usr/sbin/nft delete table ip osiris_cache

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable osiris-cache-nat >/dev/null 2>&1
    systemctl restart osiris-cache-nat
}

configurer_copie() {
    install -d -m 700 "$ETC"
    install -d -m 755 "$OPT" "$RACINE" "$RACINE/static" "$RACINE/windows" "$RACINE/tftp"
    # Le dossier deploy/cache est recopie sur le cache : on peut ensuite relancer
    # l'installation depuis la copie, sans le depot. Rien a recopier si l'on
    # tourne deja depuis elle.
    if [ "$ICI" != "$OPT" ]; then
        install -m 755 "$ICI/osiris-cache-sync.sh" "$ICI/installer-cache.sh" "$OPT/"
        install -m 644 "$ICI/osiris-cache-sync.service" "$ICI/osiris-cache-sync.timer" "$ICI/README.md" "$OPT/"
    fi
    install -m 644 "$OPT/osiris-cache-sync.service" "$OPT/osiris-cache-sync.timer" /etc/systemd/system/
    [ -f "$ETC/id_ed25519" ] || ssh-keygen -q -t ed25519 -N "" -C "osiris-cache-$(hostname -s)" -f "$ETC/id_ed25519"
    local debut=${FENETRE%-*} fin=${FENETRE#*-}
    ( umask 077; cat > "$ETC/cache.conf" <<EOF
# Ecrit par installer-cache.sh - relancer le script plutot que modifier a la main.
MANAGER=$MANAGER
OSIRIS_IP=$OSIRIS_IP
SITE_JETON=$JETON
RACINE=$RACINE
CLE=$ETC/id_ed25519
HOTES_CONNUS=$ETC/known_hosts
DEBUT_FENETRE=$debut
FIN_FENETRE=$fin
DEBIT_MAX_KO=$DEBIT_MAX_KO
CARTE_SITE=$CARTE_SITE
CARTE_LIEN=$CARTE_LIEN
EOF
    )
    # La minuterie demarre la copie a l'heure de debut de la fenetre.
    install -d /etc/systemd/system/osiris-cache-sync.timer.d
    printf '[Timer]\nOnCalendar=\nOnCalendar=*-*-* %s:00\n' "$debut" \
        > /etc/systemd/system/osiris-cache-sync.timer.d/fenetre.conf
    systemctl daemon-reload
    systemctl enable --now osiris-cache-sync.timer >/dev/null 2>&1
}

# Sans l'empreinte du manager, une machine qui se ferait passer pour lui servirait
# ses propres images a tous les PC du site. On la compare donc a celle qu'OSIRIS
# affiche lui-meme, avant de lui faire confiance.
enregistrer_empreinte() {
    local vue
    ssh-keyscan -t ed25519 "$MANAGER" 2>/dev/null > "$ETC/known_hosts.nouveau" || true
    [ -s "$ETC/known_hosts.nouveau" ] || refus "le manager $MANAGER ne repond pas en SSH (port 22) depuis ce cache"
    vue=$(ssh-keygen -lf "$ETC/known_hosts.nouveau" | awk '{print $2}')
    if [ -z "$EMPREINTE" ]; then
        echo "Empreinte SSH presentee par $MANAGER : $vue"
        echo "Sur OSIRIS, la comparer a : ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub"
        read -r -p "Les deux sont-elles identiques ? (oui/non) " reponse
        [ "$reponse" = "oui" ] || { rm -f "$ETC/known_hosts.nouveau"; refus "empreinte non confirmee : on ne fait pas confiance a $MANAGER"; }
    elif [ "$vue" != "$EMPREINTE" ]; then
        rm -f "$ETC/known_hosts.nouveau"
        refus "l'empreinte de $MANAGER ($vue) n'est pas celle attendue ($EMPREINTE). Ne pas continuer : ce n'est peut-etre pas OSIRIS."
    fi
    mv "$ETC/known_hosts.nouveau" "$ETC/known_hosts"
    vert "empreinte de $MANAGER enregistree"
}

installer() {
    lire_options "$@"
    [ "$(id -u)" = 0 ] || refus "a lancer en root"
    command -v apt-get >/dev/null || refus "Debian ou Ubuntu requis (apt-get absent)"

    etape "Paquets"
    DEBIAN_FRONTEND=noninteractive apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
        dnsmasq caddy samba rsync curl nftables iputils-arping busybox openssh-client iproute2

    etape "Carte site ($CARTE_SITE)"
    garde_fou_carte_site
    configurer_carte_site

    etape "Manager ($MANAGER)"
    install -d -m 700 "$ETC"
    enregistrer_empreinte

    etape "Copie de nuit"
    configurer_copie
    etape "DHCP et TFTP de la prise"
    configurer_dhcp
    etape "Relais vers OSIRIS"
    configurer_relais
    etape "Partage des images"
    configurer_partage
    etape "Sortie des PC (NAT)"
    configurer_nat

    etape "A faire sur OSIRIS"
    echo "1. Autoriser ce cache a copier (une seule ligne, en root sur OSIRIS) :"
    echo
    echo "   deploy/cache/autoriser-cache.sh '$(cat "$ETC/id_ed25519.pub")'"
    echo
    echo "2. Puis, ici : $OPT/osiris-cache-sync.sh --maintenant   (premiere copie)"
    echo "3. Enfin    : $OPT/installer-cache.sh verifier"
    [ -z "$DNS" ] && rouge "ATTENTION : aucun DNS donne aux PC (--dns). Sans les DNS du domaine, la jonction AD echouera."
    true
}

# ── Verification ────────────────────────────────────────────────────────────
# Chaque ligne dit ce qui est verifie, et si ca ne va pas, quoi faire. C'est la
# premiere chose a lancer quand un PC du site ne demarre pas sur le reseau.

verifier() {
    local ko=0
    ok()  { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
    pb()  { printf '  \033[31mKO\033[0m   %s\n       -> %s\n' "$1" "$2"; ko=$((ko + 1)); }
    [ -f "$ETC/cache.conf" ] || refus "cache non installe ($ETC/cache.conf absent)"
    # shellcheck source=/dev/null
    . "$ETC/cache.conf"

    etape "Services"
    for s in dnsmasq caddy smbd osiris-cache-nat osiris-cache-sync.timer; do
        if systemctl is-active -q "$s"; then ok "$s actif"
        else pb "$s arrete" "journalctl -u $s -n 30   puis   systemctl restart $s"; fi
    done

    etape "Prise d'installation"
    if ip -4 addr show "$CARTE_SITE" 2>/dev/null | grep -q " $OSIRIS_IP/"; then ok "$CARTE_SITE porte $OSIRIS_IP"
    else pb "$CARTE_SITE ne porte pas $OSIRIS_IP" "relancer installer-cache.sh installer avec les memes options"; fi
    if ip link show "$CARTE_SITE" 2>/dev/null | grep -q LOWER_UP; then ok "cable present sur $CARTE_SITE"
    else pb "pas de cable sur $CARTE_SITE" "brancher la prise d'installation (ou un PC en direct)"; fi

    # La liaison d'abord : sans elle, les fichiers ne peuvent pas arriver, et
    # l'operateur qui suit la liste dans l'ordre doit tomber sur la cause, pas
    # sur ses consequences.
    etape "Liaison avec OSIRIS"
    if curl -sf --max-time 10 "http://$OSIRIS_IP/boot" | grep -q '#!ipxe'; then ok "le relais joint OSIRIS (script de demarrage recu)"
    else pb "le relais ne joint pas OSIRIS" "verifier que $MANAGER est joignable en HTTP (port 80) depuis ce cache : curl -I http://$MANAGER/boot"; fi
    if timeout 20 rsync -e "ssh -i $CLE -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$HOTES_CONNUS" \
            "osiris-cache@$MANAGER::tftp/" >/dev/null 2>&1; then ok "la copie de nuit est autorisee par OSIRIS"
    else pb "OSIRIS refuse la copie (SSH)" "la cle de ce cache est-elle autorisee ? sur OSIRIS : deploy/cache/autoriser-cache.sh '$(cat "$CLE.pub" 2>/dev/null)'"; fi

    etape "Fichiers servis aux PC"
    for f in tftp/ipxe.efi static/wimboot static/winpe/sources/boot.wim windows/curl.exe; do
        if [ -s "$RACINE/$f" ]; then ok "$f present"
        else pb "$f absent" "la copie depuis OSIRIS n'a pas encore abouti : $OPT/osiris-cache-sync.sh --maintenant"; fi
    done
    if [ -n "$(find "$RACINE/windows" -maxdepth 1 -type f \( -iname "*.wim" -o -iname "*.esd" \) -print -quit)" ]; then ok "au moins une image Windows"
    else pb "aucune image Windows" "premiere copie inachevee ? voir l'onglet Sites d'OSIRIS"; fi

    etape "Bilan"
    if [ $ko -eq 0 ]; then vert "Tout est en ordre."
    else rouge "$ko point(s) a corriger, dans l'ordre ci-dessus."; fi
    [ $ko -eq 0 ]
}

case "${1:-}" in
    installer) shift; installer "$@" ;;
    verifier)  verifier ;;
    *) sed -n '5,20p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
