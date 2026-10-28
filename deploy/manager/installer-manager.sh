#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
#
# Installe OSIRIS (le manager) sur un Debian 12 neuf, depuis le depot clone en
# /opt/osiris. Voir deploy/manager/README.md.
#
#   installer-manager.sh installer --adresse-pc <ip> --adresse-admin <ip|nom> [options]
#   installer-manager.sh verifier
#
#   --adresse-pc <ip>        OSIRIS_IP : l'adresse a laquelle les PC joignent OSIRIS
#   --adresse-admin <ip|nom> adresse de l'interface pour les administrateurs (HTTPS)
#   --mode manager-seul      (defaut) les PC demarrent derriere des caches de site,
#                            qui portent --adresse-pc ; ce serveur n'a ni DHCP ni TFTP
#   --mode tout-en-un        ce serveur fait aussi le DHCP, le TFTP et le partage
#                            des images sur --carte-installation, qui porte deja
#                            --adresse-pc
#   --carte-installation <if>   (tout-en-un) carte du reseau d'installation
#   --dns <ip,ip>            (tout-en-un) DNS donnes aux PC (ceux du domaine)
#   --reseaux-admin <cidr,...>  reseaux autorises sur l'interface (defaut : prives)
#   --email-admin <adresse>  compte administrateur initial (defaut admin@osiris.local)
#
# Peut etre relance : rien n'est ecrase qui ne doive l'etre. Le .env existant, en
# particulier, n'est JAMAIS regenere : il porte la cle qui dechiffre les mots de
# passe en base.
set -euo pipefail

DEPOT=/opt/osiris
ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Binaires de demarrage reseau, telecharges aux sources officielles et verifies.
# Changer de version = changer l'URL ET l'empreinte, apres un essai sur le banc
# (deploy/banc-test) jusqu'au chargement de WinPE.
IPXE_URL=https://github.com/ipxe/ipxe/releases/download/v2.0.0/ipxeboot.tar.gz
IPXE_SHA256=01a526d4cc791fc30362259c609d6c506cc64a7bdff51b9a5eb788354e17eee1
WIMBOOT_URL=https://github.com/ipxe/wimboot/releases/download/v2.9.0/wimboot
WIMBOOT_SHA256=5f067ccdc4d084d5bf77b6c853bd0f8402dfc2b4cd1b103d358993ae97fae8e3

rouge() { printf '\033[31m%s\033[0m\n' "$*"; }
vert()  { printf '\033[32m%s\033[0m\n' "$*"; }
etape() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
refus() { rouge "REFUS : $*" >&2; exit 1; }

ADRESSE_PC="" ADRESSE_ADMIN="" MODE=manager-seul CARTE="" DNS=""
RESEAUX_ADMIN="10.0.0.0/8 172.16.0.0/12 192.168.0.0/16" EMAIL_ADMIN=admin@osiris.local

lire_options() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --adresse-pc)         ADRESSE_PC=$2; shift 2 ;;
            --adresse-admin)      ADRESSE_ADMIN=$2; shift 2 ;;
            --mode)               MODE=$2; shift 2 ;;
            --carte-installation) CARTE=$2; shift 2 ;;
            --dns)                DNS=$2; shift 2 ;;
            --reseaux-admin)      RESEAUX_ADMIN=${2//,/ }; shift 2 ;;
            --email-admin)        EMAIL_ADMIN=$2; shift 2 ;;
            *) refus "option inconnue : $1" ;;
        esac
    done
    [[ "$ADRESSE_PC" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || refus "--adresse-pc attend une adresse IPv4 (l'OSIRIS_IP que verront les PC)"
    [ -n "$ADRESSE_ADMIN" ] || refus "--adresse-admin manquant (adresse ou nom de ce serveur pour les administrateurs)"
    case "$MODE" in
        manager-seul) ;;
        tout-en-un) [ -n "$CARTE" ] || refus "--mode tout-en-un demande --carte-installation" ;;
        *) refus "--mode attend manager-seul ou tout-en-un" ;;
    esac
}

# Compte qui administre : il garde la main sur le code et les fichiers generes.
ADMIN_UNIX=${SUDO_USER:-root}
en_admin() { if [ "$ADMIN_UNIX" = root ]; then "$@"; else sudo -u "$ADMIN_UNIX" -H "$@"; fi; }

# ── Etapes ──────────────────────────────────────────────────────────────────

paquets() {
    local liste=(git python3-venv postgresql redis-server caddy rsync curl acl openssl
                 p7zip-full innoextract xorriso wimtools)
    [ "$MODE" = tout-en-un ] && liste+=(dnsmasq samba iputils-arping busybox)
    DEBIAN_FRONTEND=noninteractive apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q "${liste[@]}"
    # Node 22 : Debian 12 ne fournit que Node 18, trop ancien pour le build (Vite).
    local majeur; majeur=$(node --version 2>/dev/null | sed -E 's/^v([0-9]+).*/\1/' || true)
    if [ "${majeur:-0}" -lt 22 ]; then
        curl -fsSL https://deb.nodesource.com/setup_22.x -o /tmp/nodesource_setup.sh
        bash /tmp/nodesource_setup.sh >/dev/null
        DEBIAN_FRONTEND=noninteractive apt-get install -y -q nodejs
    fi
}

compte_de_service() {
    # L'API repond a des machines non authentifiees : jamais sous un compte qui a sudo.
    id osiris >/dev/null 2>&1 || useradd --system --user-group --home-dir /var/lib/osiris \
        --create-home --shell /usr/sbin/nologin osiris
    [ "$ADMIN_UNIX" != root ] && usermod -aG osiris "$ADMIN_UNIX"
    install -d -m 2775 -o osiris -g osiris /srv/data /srv/data/windows /srv/data/windows/winpe-drivers
    install -d -m 2770 -o osiris -g osiris /srv/data/captures
    install -d -m 755 /srv/tftp
    for d in "$DEPOT/backend/static" /srv/data; do
        install -d "$d"
        setfacl -R -m "u:osiris:rwX" "$d"
        find "$d" -type d -exec setfacl -m "d:u:osiris:rwX" {} +
        if [ "$ADMIN_UNIX" != root ]; then
            setfacl -R -m "u:$ADMIN_UNIX:rwX" "$d"
            find "$d" -type d -exec setfacl -m "d:u:$ADMIN_UNIX:rwX" {} +
        fi
    done
    # Les images : modifiables par OSIRIS et l'administrateur, par personne d'autre.
    setfacl -m o::rx -m d:o::rx /srv/data/windows
}

fichier_env() {
    local env="$DEPOT/backend/.env"
    if [ -f "$env" ]; then
        echo "$env existe deja : conserve tel quel (il porte la cle de chiffrement)"
        return
    fi
    local pw_base pw_admin fernet jwt
    pw_base=$(openssl rand -hex 16)
    pw_admin=$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)
    fernet=$("$DEPOT/backend/venv/bin/python" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    jwt=$(openssl rand -hex 32)
    sed -e "s|^DB_PASSWORD=.*|DB_PASSWORD=$pw_base|" \
        -e "s|^FERNET_KEY=.*|FERNET_KEY=$fernet|" \
        -e "s|^JWT_SECRET=.*|JWT_SECRET=$jwt|" \
        -e "s|^ADMIN_EMAIL=.*|ADMIN_EMAIL=$EMAIL_ADMIN|" \
        -e "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=$pw_admin|" \
        -e "s|^OSIRIS_BASE_URL=.*|OSIRIS_BASE_URL=http://$ADRESSE_PC|" \
        -e "s|^OSIRIS_IP=.*|OSIRIS_IP=$ADRESSE_PC|" \
        -e "s|^ALLOWED_ORIGINS=.*|ALLOWED_ORIGINS=|" \
        -e "s|^VITE_API_URL=.*|VITE_API_URL=|" \
        "$DEPOT/.env.example" > "$env"
    chown "$ADMIN_UNIX":osiris "$env"
    chmod 640 "$env"
    # Montre une fois : l'administrateur le change a la premiere connexion.
    echo "$pw_admin" > /root/osiris-mot-de-passe-initial
    chmod 600 /root/osiris-mot-de-passe-initial
    vert ".env cree (secrets generes) ; mot de passe admin initial dans /root/osiris-mot-de-passe-initial"
}

lire_env() { grep -E "^$1=" "$DEPOT/backend/.env" | head -1 | cut -d= -f2-; }

base_de_donnees() {
    local u pw n
    u=$(lire_env DB_USER); pw=$(lire_env DB_PASSWORD); n=$(lire_env DB_NAME)
    if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$u'" | grep -q 1; then
        sudo -u postgres psql -q -c "CREATE USER \"$u\" PASSWORD '$pw'"
    fi
    if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$n'" | grep -q 1; then
        sudo -u postgres createdb -O "$u" "$n"
    fi
    echo "base $n prete (compte $u)"
}

python_et_frontend() {
    # Le .lock, pas le .txt : les versions avec lesquelles OSIRIS passe ses tests.
    [ -x "$DEPOT/backend/venv/bin/python" ] || en_admin python3 -m venv "$DEPOT/backend/venv"
    en_admin "$DEPOT/backend/venv/bin/pip" install -q -r "$DEPOT/backend/requirements.lock"
    [ -f "$DEPOT/frontend/.env" ] || en_admin cp "$DEPOT/frontend/.env.example" "$DEPOT/frontend/.env"
    ( cd "$DEPOT/frontend" && en_admin npm ci --silent && en_admin npm run build --silent >/dev/null )
    # Le code doit etre lisible par le compte de service.
    find "$DEPOT/backend" -path "$DEPOT/backend/venv" -prune -o ! -name .env -type f ! -perm -o=r -print0 \
        | xargs -0 -r chmod o+r
    echo "environnement Python et interface construits"
}

# Telecharge, verifie l'empreinte, et seulement alors met en place.
telecharger_verifie() {
    local url=$1 attendu=$2 dest=$3 vu
    curl -fsSL -o "$dest.tmp" "$url" || refus "telechargement impossible : $url"
    vu=$(sha256sum "$dest.tmp" | cut -d' ' -f1)
    if [ "$vu" != "$attendu" ]; then
        rm -f "$dest.tmp"
        refus "empreinte inattendue pour $url ($vu au lieu de $attendu) : fichier refuse"
    fi
    mv "$dest.tmp" "$dest"
}

demarrage_reseau() {
    local tmp; tmp=$(mktemp -d)
    telecharger_verifie "$IPXE_URL" "$IPXE_SHA256" "$tmp/ipxeboot.tar.gz"
    tar xzf "$tmp/ipxeboot.tar.gz" -C "$tmp" ipxeboot/x86_64/ipxe.efi
    install -m 644 "$tmp/ipxeboot/x86_64/ipxe.efi" /srv/tftp/ipxe.efi
    telecharger_verifie "$WIMBOOT_URL" "$WIMBOOT_SHA256" "$tmp/wimboot"
    install -m 644 -o osiris -g osiris "$tmp/wimboot" "$DEPOT/backend/static/wimboot"
    rm -rf "$tmp"
    echo "ipxe.efi (iPXE v2.0.0) et wimboot (v2.9.0) en place, empreintes verifiees"
}

# Le Caddyfile est derive du modele du depot : on n'y recopie pas la liste des
# routes, qui ne pourrait que diverger. On n'y change que les adresses, les
# certificats (internes tant qu'aucun n'est fourni) et les reseaux d'administration.
caddy_config() {
    [ -f /etc/caddy/Caddyfile ] && [ ! -f /etc/caddy/Caddyfile.avant-osiris ] \
        && cp -p /etc/caddy/Caddyfile /etc/caddy/Caddyfile.avant-osiris
    ADRESSE_PC=$ADRESSE_PC ADRESSE_ADMIN=$ADRESSE_ADMIN RESEAUX_ADMIN=$RESEAUX_ADMIN \
    python3 - "$DEPOT/Caddyfile.example" > /etc/caddy/Caddyfile.nouveau <<'PY'
import os, re, sys
texte = open(sys.argv[1]).read()
pc, admin = os.environ["ADRESSE_PC"], os.environ["ADRESSE_ADMIN"]
reseaux = os.environ["RESEAUX_ADMIN"]

# Decoupe en blocs de premier niveau pour retirer ceux du nom d'exemple : le nom
# d'administration, s'il y en a un, est porte par le bloc « IP » ci-dessous.
blocs, prof, debut = [], 0, 0
for i, c in enumerate(texte):
    if c == "{":
        prof += 1
    elif c == "}":
        prof -= 1
        if prof == 0:
            blocs.append(texte[debut:i + 1]); debut = i + 1
reste = texte[debut:]
garde = []
for b in blocs:
    entete = b.strip().splitlines()
    entete = next((l for l in entete if l.strip() and not l.strip().startswith("#")), "")
    if "osiris.example.local" in entete:
        continue
    garde.append(b)
texte = "".join(garde) + reste
texte = texte.replace("https://10.0.0.1", "https://" + admin)
texte = texte.replace("http://10.0.0.1", "http://" + pc)
texte = re.sub(r"tls /etc/caddy/certs/\S+ /etc/caddy/certs/\S+", "tls internal", texte)
texte = re.sub(r"not remote_ip [^\n]*", "not remote_ip " + reseaux + " 127.0.0.1/32 ::1", texte)
print("# Genere par deploy/manager/installer-manager.sh depuis Caddyfile.example\n" + texte)
PY
    caddy validate --config /etc/caddy/Caddyfile.nouveau --adapter caddyfile >/dev/null 2>&1 \
        || { caddy validate --config /etc/caddy/Caddyfile.nouveau --adapter caddyfile; refus "Caddyfile genere invalide"; }
    mv /etc/caddy/Caddyfile.nouveau /etc/caddy/Caddyfile
    systemctl enable caddy >/dev/null 2>&1
    systemctl reload-or-restart caddy
}

# manager-seul : l'adresse des PC est portee par les caches, pas par ce serveur.
# On la pose sur la boucle locale pour que l'API puisse controler ses propres
# routes (elle appelle OSIRIS_BASE_URL au demarrage) sans qu'elle soit annoncee
# sur le reseau.
adresse_locale() {
    cat > /etc/systemd/system/osiris-adresse-pc.service <<EOF
[Unit]
Description=Adresse des PC d'OSIRIS sur la boucle locale (mode manager-seul)
Before=caddy.service osiris-api.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'ip -4 addr show dev lo | grep -q " $ADRESSE_PC/" || ip addr add $ADRESSE_PC/32 dev lo'
ExecStop=-/sbin/ip addr del $ADRESSE_PC/32 dev lo

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable --now osiris-adresse-pc >/dev/null 2>&1
}

# tout-en-un : meme garde-fou que pour un cache. La carte doit deja porter
# l'adresse des PC, et personne d'autre ne doit y distribuer d'adresses.
reseau_installation() {
    ip -4 addr show "$CARTE" 2>/dev/null | grep -q " $ADRESSE_PC/" \
        || refus "$CARTE ne porte pas $ADRESSE_PC : en tout-en-un, la carte d'installation doit deja avoir cette adresse"
    if ! systemctl is-active -q dnsmasq || ! grep -qs "interface=$CARTE" /etc/dnsmasq.d/osiris.conf; then
        if busybox udhcpc -i "$CARTE" -n -q -t 3 -T 2 -s /bin/true >/dev/null 2>&1; then
            refus "un serveur DHCP repond deja sur $CARTE : deux DHCP sur un reseau, c'est des postes sans adresse. Le couper, ou utiliser --mode manager-seul."
        fi
    fi
    local base=${ADRESSE_PC%.*} dernier=${ADRESSE_PC##*.} plage
    if [ "$dernier" -lt 100 ] || [ "$dernier" -gt 199 ]; then plage="$base.100,$base.199"; else plage="$base.20,$base.99"; fi
    cat > /etc/dnsmasq.d/osiris.conf <<EOF
# OSIRIS tout-en-un : DHCP et TFTP du reseau d'installation, sur $CARTE seulement.
port=0
interface=$CARTE
bind-interfaces
log-dhcp
dhcp-authoritative
dhcp-range=$plage,255.255.255.0,2h
${DNS:+dhcp-option=6,$DNS}
dhcp-match=set:is_ipxe,175
dhcp-boot=tag:!is_ipxe,ipxe.efi,$ADRESSE_PC
dhcp-boot=tag:is_ipxe,http://$ADRESSE_PC/boot
enable-tftp
tftp-root=/srv/tftp
EOF
    systemctl enable dnsmasq >/dev/null 2>&1
    systemctl restart dnsmasq
    [ -f /etc/samba/smb.conf ] && [ ! -f /etc/samba/smb.conf.avant-osiris ] \
        && cp -p /etc/samba/smb.conf /etc/samba/smb.conf.avant-osiris
    cat > /etc/samba/smb.conf <<EOF
# OSIRIS : les images en lecture seule, et le depot des captures en ecriture.
[global]
    server role = standalone server
    map to guest = Bad User
    interfaces = $CARTE
    bind interfaces only = yes
    disable netbios = yes
    smb ports = 445
    log file = /var/log/samba/log.%m

[windows]
    path = /srv/data/windows
    guest ok = yes
    read only = yes
    force user = osiris

# Seule la capture ecrit, ici ; OSIRIS range l'image dans « windows » a la fin.
[captures]
    path = /srv/data/captures
    guest ok = yes
    read only = no
    browseable = no
    force user = osiris
EOF
    systemctl enable smbd >/dev/null 2>&1
    systemctl restart smbd
}

# Les caches de site recopient chaque nuit, en lecture seule (deploy/cache).
acces_caches() {
    id osiris-cache >/dev/null 2>&1 || useradd --system --home-dir /var/lib/osiris-cache \
        --create-home --shell /bin/sh osiris-cache
    install -d -m 755 /etc/osiris
    install -m 644 "$DEPOT/deploy/cache/rsyncd-cache.conf.example" /etc/osiris/rsyncd-cache.conf
    install -d -m 700 -o osiris-cache -g osiris-cache /var/lib/osiris-cache/.ssh
}

services() {
    install -m 644 "$DEPOT/osiris-api.service" "$DEPOT/osiris-worker.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable osiris-api osiris-worker >/dev/null 2>&1
    systemctl restart osiris-api osiris-worker
    local essais=0
    until curl -sf http://127.0.0.1:8000/health >/dev/null; do
        essais=$((essais + 1))
        [ $essais -ge 30 ] && refus "l'API ne repond pas apres 60 s : journalctl -u osiris-api -n 50"
        sleep 2
    done
    vert "API demarree"
}

installer() {
    lire_options "$@"
    [ "$(id -u)" = 0 ] || refus "a lancer avec sudo"
    [ "$ICI" = "$DEPOT/deploy/manager" ] || refus "le depot doit etre clone en $DEPOT (les services y sont attaches)"
    etape "Paquets";               paquets
    etape "Compte de service";     compte_de_service
    etape "Python et interface";   python_et_frontend
    etape "Configuration (.env)";  fichier_env
    etape "Base de donnees";       base_de_donnees
    etape "Demarrage reseau (iPXE, wimboot)"; demarrage_reseau
    if [ "$MODE" = manager-seul ]; then
        etape "Adresse des PC (boucle locale)"; adresse_locale
    else
        etape "Reseau d'installation ($CARTE)"; reseau_installation
    fi
    etape "Acces des caches de site"; acces_caches
    etape "Services";              services
    etape "Frontal (Caddy)";       caddy_config

    etape "Ensuite"
    echo "1. Ouvrir https://$ADRESSE_ADMIN (certificat interne de Caddy : l'accepter, ou en installer un)"
    echo "2. Se connecter : $EMAIL_ADMIN / le mot de passe de /root/osiris-mot-de-passe-initial,"
    echo "   le changer aussitot, puis supprimer ce fichier"
    echo "3. Televerser une ISO Windows (onglet Images) : OSIRIS en tire WinPE et l'image"
    echo "4. Controle complet : sudo $DEPOT/deploy/manager/installer-manager.sh verifier"
}

# ── Verification ────────────────────────────────────────────────────────────

verifier() {
    local ko=0 pc
    ok() { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
    pb() { printf '  \033[31mKO\033[0m   %s\n       -> %s\n' "$1" "$2"; ko=$((ko + 1)); }
    [ -f "$DEPOT/backend/.env" ] || refus "OSIRIS non installe ($DEPOT/backend/.env absent)"
    pc=$(lire_env OSIRIS_IP)

    etape "Services"
    for s in postgresql redis-server osiris-api osiris-worker caddy; do
        if systemctl is-active -q "$s"; then ok "$s actif"
        else pb "$s arrete" "journalctl -u $s -n 50   puis   systemctl restart $s"; fi
    done
    if systemctl is-enabled -q dnsmasq 2>/dev/null; then
        systemctl is-active -q dnsmasq && ok "dnsmasq actif (tout-en-un)" || pb "dnsmasq arrete" "journalctl -u dnsmasq -n 30"
    fi

    etape "API"
    local sante; sante=$(curl -sf http://127.0.0.1:8000/health || true)
    if [ -z "$sante" ]; then pb "l'API ne repond pas" "journalctl -u osiris-api -n 50"
    else
        grep -q '"db":"ok"' <<<"$sante" && ok "base de donnees joignable" || pb "base de donnees en erreur" "systemctl status postgresql ; verifier DB_* dans backend/.env"
        if grep -q '"winpe":"ok"' <<<"$sante"; then ok "WinPE pret"
        else pb "WinPE absent ou perime" "televerser une ISO Windows (onglet Images) : OSIRIS en tire WinPE"; fi
    fi

    etape "Ce que voient les PC (http://$pc)"
    if curl -sf --max-time 5 "http://$pc/boot" | grep -q '#!ipxe'; then ok "script de demarrage servi par Caddy"
    else pb "http://$pc/boot ne repond pas" "Caddy sert-il le bloc http://$pc ? journalctl -u caddy -n 30"; fi
    [ "$(sha256sum /srv/tftp/ipxe.efi 2>/dev/null | cut -d' ' -f1)" ] && ok "ipxe.efi present" \
        || pb "ipxe.efi absent de /srv/tftp" "relancer l'installation (etape demarrage reseau)"
    [ "$(sha256sum "$DEPOT/backend/static/wimboot" 2>/dev/null | cut -d' ' -f1)" = "$WIMBOOT_SHA256" ] && ok "wimboot verifie" \
        || pb "wimboot absent ou different" "relancer l'installation (etape demarrage reseau)"

    etape "Bilan"
    if [ $ko -eq 0 ]; then vert "Tout est en ordre."; else rouge "$ko point(s) a corriger, dans l'ordre ci-dessus."; fi
    [ $ko -eq 0 ]
}

case "${1:-}" in
    installer) shift; installer "$@" ;;
    verifier)  verifier ;;
    *) sed -n '5,22p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
