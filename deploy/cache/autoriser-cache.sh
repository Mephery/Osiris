#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
#
# Cote OSIRIS : autorise un cache de site a faire sa copie de nuit.
#
#   autoriser-cache.sh '<cle publique du cache>'     ajoute (ou laisse) la cle
#   autoriser-cache.sh --retirer '<commentaire>'     retire la cle de ce cache
#
# La cle est bridee : elle ne peut lancer que rsync, en lecture seule, sur les
# dossiers de /etc/osiris/rsyncd-cache.conf. Ecrire cette bride a la main, c'est
# risquer une cle qui ouvre un shell sur OSIRIS ; ce script ne laisse pas le choix.
set -euo pipefail

FICHIER=/var/lib/osiris-cache/.ssh/authorized_keys
BRIDE='command="rsync --server --daemon --config=/etc/osiris/rsyncd-cache.conf .",restrict'

[ "$(id -u)" = 0 ] || { echo "a lancer en root" >&2; exit 1; }
id osiris-cache >/dev/null 2>&1 || { echo "compte osiris-cache absent : voir deploy/cache/README.md (cote OSIRIS)" >&2; exit 1; }
[ -f /etc/osiris/rsyncd-cache.conf ] || { echo "/etc/osiris/rsyncd-cache.conf absent : voir deploy/cache/README.md" >&2; exit 1; }
install -d -m 700 -o osiris-cache -g osiris-cache "$(dirname "$FICHIER")"
touch "$FICHIER"; chown osiris-cache: "$FICHIER"; chmod 600 "$FICHIER"

if [ "${1:-}" = "--retirer" ]; then
    commentaire=${2:?commentaire de la cle a retirer, ex. osiris-cache-paris}
    grep -v " $commentaire\$" "$FICHIER" > "$FICHIER.nouveau" || true
    mv "$FICHIER.nouveau" "$FICHIER"; chown osiris-cache: "$FICHIER"; chmod 600 "$FICHIER"
    echo "cle « $commentaire » retiree : ce cache ne peut plus copier"
    exit 0
fi

cle=${1:?cle publique du cache, telle qu affichee par installer-cache.sh}
# Une seule cle ed25519, rien d'autre : surtout pas d'options glissees devant.
[[ "$cle" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+\ [A-Za-z0-9._@-]+$ ]] \
    || { echo "ce n'est pas une cle ed25519 de cache (attendu : ssh-ed25519 AAAA... osiris-cache-<nom>)" >&2; exit 1; }
corps=$(awk '{print $2}' <<<"$cle")
if grep -q "$corps" "$FICHIER"; then
    echo "cle deja autorisee"
else
    echo "$BRIDE $cle" >> "$FICHIER"
    echo "cle autorisee : « $(awk '{print $3}' <<<"$cle") » peut copier, en lecture seule"
fi
