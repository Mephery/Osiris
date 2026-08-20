#!/usr/bin/env bash
# Installe le certificat renouvele la ou Caddy le lit, puis le lui fait relire.
#
# Caddy tourne sous l'utilisateur `caddy` et /etc/letsencrypt est en 700 root :
# il ne peut pas lire directement les fichiers de certbot. On recopie donc, plutot
# que d'ouvrir l'arborescence de letsencrypt a un autre utilisateur.
#
# Appele automatiquement par certbot APRES chaque renouvellement reussi
# (renewal-hooks/deploy). Sans ce crochet, le certificat serait bien renouvele sur
# le disque et Caddy continuerait a servir l'ancien jusqu'a son expiration — une
# panne differee de trois mois, invisible le jour du renouvellement.
set -euo pipefail

SOURCE=/etc/letsencrypt/live/osiris
CIBLE=/etc/caddy/certs

# Ne rien faire si c'est un AUTRE certificat qui vient d'etre renouvele.
if [ -n "${RENEWED_LINEAGE:-}" ] && [ "$RENEWED_LINEAGE" != "$SOURCE" ]; then
    exit 0
fi

install -o caddy -g caddy -m 644 "$SOURCE/fullchain.pem" "$CIBLE/osiris-le.crt"
install -o caddy -g caddy -m 600 "$SOURCE/privkey.pem"   "$CIBLE/osiris-le.key"

systemctl reload caddy
echo "Certificat installe pour Caddy et configuration rechargee."
