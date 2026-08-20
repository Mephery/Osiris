#!/usr/bin/env bash
# Crochets DNS-01 pour certbot, via l'API LiveDNS de Gandi.
#
# OSIRIS n'est pas joignable depuis internet : la validation HTTP-01, qui suppose
# que Let's Encrypt vienne frapper sur le port 80, est donc impossible. DNS-01 ne
# demande qu'un enregistrement TXT temporaire — aucune exposition, aucun port
# ouvert.
#
# Ecrit en shell explicite plutot qu'avec un greffon tiers : une trentaine de
# lignes lisibles et deboguables a la main, sans dependance PyPI a suivre.
#
#   certbot-gandi.sh auth      cree le TXT et ATTEND sa propagation
#   certbot-gandi.sh cleanup   le supprime
#
# certbot fournit CERTBOT_DOMAIN et CERTBOT_VALIDATION dans l'environnement.
set -euo pipefail

CONF=${CONF:-/etc/letsencrypt/gandi.ini}
[ -r "$CONF" ] || { echo "config illisible : $CONF" >&2; exit 1; }
# shellcheck disable=SC1090
set -a; . "$CONF"; set +a
: "${GANDI_TOKEN:?GANDI_TOKEN absent de $CONF}"

# La zone est declaree, pas devinee : deduire « data-expertise.com » de
# « osiris.data-expertise.com » suppose de connaitre la liste des suffixes
# publics, et se trompe silencieusement sur un .co.uk ou un sous-domaine delegue.
ZONE=${GANDI_ZONE:-data-expertise.com}
API="https://api.gandi.net/v5/livedns/domains/$ZONE/records"

: "${CERTBOT_DOMAIN:?CERTBOT_DOMAIN absent — ce script est appele par certbot}"

# Nom de l'enregistrement RELATIF a la zone.
if [ "$CERTBOT_DOMAIN" = "$ZONE" ]; then
    NOM="_acme-challenge"
else
    NOM="_acme-challenge.${CERTBOT_DOMAIN%".$ZONE"}"
fi

_curl() {
    curl -sS --max-time 30 -H "Authorization: Bearer $GANDI_TOKEN" "$@"
}

case "${1:-}" in
auth)
    : "${CERTBOT_VALIDATION:?CERTBOT_VALIDATION absent}"
    code=$(_curl -o /tmp/gandi-auth.$$ -w '%{http_code}' -X PUT "$API/$NOM/TXT" \
        -H "Content-Type: application/json" \
        -d "{\"rrset_values\":[\"$CERTBOT_VALIDATION\"],\"rrset_ttl\":300}")
    if [ "$code" != "200" ] && [ "$code" != "201" ]; then
        echo "Gandi a refuse l'ecriture (HTTP $code) :" >&2
        cat /tmp/gandi-auth.$$ >&2; echo >&2
        rm -f /tmp/gandi-auth.$$; exit 1
    fi
    rm -f /tmp/gandi-auth.$$
    echo "TXT $NOM.$ZONE ecrit."

    # On ATTEND que les serveurs faisant autorite le servent vraiment. Un `sleep`
    # fixe serait soit trop court (Let's Encrypt interroge avant publication et la
    # commande echoue sans dire pourquoi), soit inutilement long a chaque
    # renouvellement. On interroge donc chaque NS de la zone jusqu'a les voir tous
    # d'accord.
    mapfile -t NS < <(dig +short NS "$ZONE" | sed 's/\.$//')
    [ "${#NS[@]}" -gt 0 ] || { echo "aucun NS trouve pour $ZONE" >&2; exit 1; }

    for _ in $(seq 1 60); do   # 60 x 5 s = 5 min au maximum
        tous=1
        for serveur in "${NS[@]}"; do
            vu=$(dig +short "@$serveur" TXT "$NOM.$ZONE" 2>/dev/null | tr -d '"')
            case "$vu" in *"$CERTBOT_VALIDATION"*) : ;; *) tous=0 ;; esac
        done
        if [ "$tous" -eq 1 ]; then
            echo "Propage sur les ${#NS[@]} serveurs de la zone."
            exit 0
        fi
        sleep 5
    done
    echo "TXT toujours pas propage apres 5 min — la validation va echouer." >&2
    exit 1
    ;;
cleanup)
    # L'echec du nettoyage ne doit pas faire echouer un renouvellement par
    # ailleurs reussi : le TXT restant est inerte, et le prochain PUT l'ecrase.
    code=$(_curl -o /dev/null -w '%{http_code}' -X DELETE "$API/$NOM/TXT" || echo "erreur")
    echo "Suppression de $NOM.$ZONE : HTTP $code"
    ;;
*)
    echo "usage : $0 auth|cleanup" >&2; exit 1 ;;
esac
