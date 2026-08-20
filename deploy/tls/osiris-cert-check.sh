#!/usr/bin/env bash
# Etat du certificat TLS et du jeton Gandi, pour la supervision.
#
# Tourne en root (il lit le jeton) et depose un fichier d'etat SANS SECRET, que
# l'agent Zabbix peut lire sous son propre utilisateur. C'est ce decoupage qui
# evite d'avoir a donner un sudo a l'agent ou a relacher les droits du jeton.
#
# Les deux echeances surveillees se taisent en cas de panne, et c'est bien le
# probleme :
#   - un certificat expire se voit tout de suite, mais trop tard ;
#   - un jeton Gandi expire casse le RENOUVELLEMENT, sans le moindre signe, et
#     ne se manifeste que 90 jours plus tard quand le certificat meurt a son tour.
set -euo pipefail

CERT=/etc/letsencrypt/live/osiris/fullchain.pem
CONF=/etc/letsencrypt/gandi.ini
SORTIE=/var/lib/osiris/cert-status.json

install -d -m 755 "$(dirname "$SORTIE")"

_jours_restants() {   # $1 = date de fin, format accepte par `date -d`
    local fin; fin=$(date -d "$1" +%s 2>/dev/null) || { echo -1; return; }
    echo $(( (fin - $(date +%s)) / 86400 ))
}

# ── Certificat ────────────────────────────────────────────────────────────────
if [ -r "$CERT" ]; then
    fin=$(openssl x509 -in "$CERT" -noout -enddate | cut -d= -f2)
    cert_jours=$(_jours_restants "$fin")
    cert_sujet=$(openssl x509 -in "$CERT" -noout -subject | sed 's/^subject=*//')
else
    cert_jours=-1; cert_sujet="certificat absent"
fi

# ── Jeton Gandi ───────────────────────────────────────────────────────────────
jeton_ok=0; jeton_jours=-1
if [ -r "$CONF" ]; then
    set -a; . "$CONF"; set +a
    if [ -n "${GANDI_TOKEN:-}" ]; then
        # On interroge la zone qu'on doit pouvoir ECRIRE au renouvellement. Un 200
        # prouve que le jeton vit ET qu'il porte encore sur le bon domaine — c'est
        # exactement ce qui manquait le jour ou le premier jeton rendait 403.
        code=$(curl -s -o /dev/null -m 20 -w '%{http_code}' \
            -H "Authorization: Bearer $GANDI_TOKEN" \
            "https://api.gandi.net/v5/livedns/domains/${GANDI_ZONE:-data-expertise.com}" || echo 000)
        [ "$code" = "200" ] && jeton_ok=1
    fi
    [ -n "${GANDI_TOKEN_EXPIRE:-}" ] && jeton_jours=$(_jours_restants "$GANDI_TOKEN_EXPIRE")
fi

# Ecriture atomique : un fichier a moitie ecrit serait lu comme une panne.
tmp=$(mktemp)
printf '{"cert_jours":%s,"cert_sujet":"%s","jeton_ok":%s,"jeton_jours":%s,"controle":"%s"}\n' \
    "$cert_jours" "$cert_sujet" "$jeton_ok" "$jeton_jours" "$(date -Iseconds)" > "$tmp"
install -m 644 "$tmp" "$SORTIE"
rm -f "$tmp"
cat "$SORTIE"
