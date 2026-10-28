#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
#
# Copie de nuit d'un cache de site : recopie depuis OSIRIS ce qu'un PC peut
# demander, puis rend compte a OSIRIS (onglet Sites). Voir README.md.
#
#   osiris-cache-sync.sh               copie, si l'on est dans la fenetre de nuit
#   osiris-cache-sync.sh --maintenant  copie tout de suite (premiere copie, test)
#
# Configuration : /etc/osiris-cache/cache.conf (modele : cache.conf.example).
set -uo pipefail

CONF=${CONF:-/etc/osiris-cache/cache.conf}
# shellcheck source=/dev/null
. "$CONF" || { echo "configuration illisible : $CONF" >&2; exit 2; }

: "${MANAGER:?MANAGER manquant dans $CONF}"
: "${OSIRIS_IP:?OSIRIS_IP manquant dans $CONF}"
: "${SITE_JETON:?SITE_JETON manquant dans $CONF}"
RACINE=${RACINE:-/srv/osiris-cache}
CLE=${CLE:-/etc/osiris-cache/id_ed25519}
# Empreinte de la cle SSH d'OSIRIS, relevee a l'installation : sans elle, une
# machine qui se ferait passer pour OSIRIS servirait ses propres images.
HOTES_CONNUS=${HOTES_CONNUS:-/etc/osiris-cache/known_hosts}
DEBIT_MAX_KO=${DEBIT_MAX_KO:-0}
DEBUT_FENETRE=${DEBUT_FENETRE:-01:00}
FIN_FENETRE=${FIN_FENETRE:-05:00}
# Les petits d'abord : si la nuit ne suffit pas, WinPE et iPXE sont deja a jour.
read -ra MODULES <<<"${MODULES:-tftp static windows}"

# Deux copies en meme temps se marcheraient dessus (minuterie + lancement a la main).
exec 9>"/run/osiris-cache-sync.lock"
flock -n 9 || { echo "une copie est deja en cours"; exit 0; }

# Secondes jusqu'a la fin de la fenetre. La copie s'arrete la, meme inachevee :
# elle ne doit jamais deborder sur la journee, quand le lien sert aux utilisateurs.
# Ce qui a ete recu est garde (--partial-dir) et la nuit suivante reprend.
secondes_restantes() {
    local fin; fin=$(date -d "today $FIN_FENETRE" +%s)
    local maintenant; maintenant=$(date +%s)
    [ "$fin" -le "$maintenant" ] && fin=$(date -d "tomorrow $FIN_FENETRE" +%s)
    echo $(( fin - maintenant ))
}

# Vrai si l'heure courante est dans [DEBUT_FENETRE, FIN_FENETRE[, y compris pour
# une fenetre qui passe minuit (22:00 -> 05:00).
dans_la_fenetre() {
    local h d f
    h=$(date +%H%M); d=${DEBUT_FENETRE/:/}; f=${FIN_FENETRE/:/}
    h=$((10#$h)); d=$((10#$d)); f=$((10#$f))
    if [ "$d" -le "$f" ]; then [ "$h" -ge "$d" ] && [ "$h" -lt "$f" ]
    else [ "$h" -ge "$d" ] || [ "$h" -lt "$f" ]; fi
}

json_echappe() { local s=${1//\\/\\\\}; s=${s//\"/\\\"}; printf '%s' "${s//$'\n'/ }"; }

# Images Windows presentes sur le cache, sous la forme qu'OSIRIS compare aux
# siennes : nom, taille, date de modification (conservee par rsync -a).
images_json() {
    local premier=1 nom taille mtime
    printf '['
    while IFS=$'\t' read -r nom taille mtime; do
        [ $premier = 1 ] || printf ','
        premier=0
        printf '{"nom":"%s","taille":%s,"mtime":%s}' "$(json_echappe "$nom")" "$taille" "$mtime"
    done < <(find "$RACINE/windows" -maxdepth 1 -type f \( -iname '*.wim' -o -iname '*.esd' \) \
                  -printf '%f\t%s\t%Ts\n' 2>/dev/null | sort)
    printf ']'
}

# Passe par l'adresse d'OSIRIS que le cache porte lui-meme : son Caddy relaie
# vers le vrai OSIRIS, comme pour les PC. Aucun chemin reseau de plus a ouvrir.
rendre_compte() {
    local ok=$1 erreur=$2 duree=$3 octets=$4 inachevee=${5:-false} corps
    corps=$(printf '{"ok":%s,"erreur":"%s","inachevee":%s,"duree_s":%s,"octets_recus":%s,"images":%s}' \
        "$ok" "$(json_echappe "$erreur")" "$inachevee" "$duree" "$octets" "$(images_json)")
    if ! curl -sf --max-time 30 -X POST -H "Content-Type: application/json" \
            -H "X-Osiris-Site-Jeton: $SITE_JETON" --data "$corps" \
            "http://$OSIRIS_IP/sites/rapport" >/dev/null; then
        echo "compte rendu refuse ou OSIRIS injoignable : l'onglet Sites ne verra pas cette copie" >&2
        return 1
    fi
}

if [ "${1:-}" != "--maintenant" ]; then
    # Hors fenetre (cache rallume en journee, lancement oublie) : on ne copie pas.
    dans_la_fenetre || {
        echo "hors de la fenetre de nuit ($DEBUT_FENETRE-$FIN_FENETRE) : rien a faire"; exit 0; }
fi

debut=$(date +%s)
octets=0
erreur=""
inachevee=false
for module in "${MODULES[@]}"; do
    mkdir -p "$RACINE/$module"
    restant=$(secondes_restantes)
    [ "${1:-}" = "--maintenant" ] && restant=$(( 24 * 3600 ))
    # --delay-updates : les fichiers changes ne prennent leur place qu'a la fin du
    # module, ensemble. Un PC qui demarre pendant la copie voit l'ancien WinPE OU
    # le nouveau, jamais un melange des deux. Un PC deja en train de lire une image
    # garde l'ancienne jusqu'au bout : rsync remplace par renommage.
    # --no-owner --no-group : les fichiers appartiennent a root sur le cache, pas a
    # des numeros de comptes du manager qui ne designent personne ici.
    sortie=$(timeout "$restant" rsync -a --no-owner --no-group --delete-delay --delay-updates \
        --partial-dir=.osiris-partiel --timeout=600 --stats \
        --bwlimit="$DEBIT_MAX_KO" \
        -e "ssh -i $CLE -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$HOTES_CONNUS" \
        "osiris-cache@$MANAGER::$module/" "$RACINE/$module/" 2>&1)
    code=$?
    recus=$(sed -n 's/^Total bytes received: \([0-9,.]*\).*/\1/p' <<<"$sortie" | tr -d ',.')
    octets=$(( octets + ${recus:-0} ))
    if [ $code -eq 124 ]; then
        erreur="fenetre de nuit terminee pendant le module $module (reprise la nuit prochaine)"
        inachevee=true
        break
    elif [ $code -ne 0 ]; then
        erreur="rsync $module : code $code - $(tail -n 2 <<<"$sortie" | tr '\n' ' ')"
        break
    fi
    echo "$module : a jour (${recus:-0} octets recus)"
done
duree=$(( $(date +%s) - debut ))

if [ -z "$erreur" ]; then
    echo "copie terminee en ${duree} s"
    rendre_compte true "" "$duree" "$octets" || exit 1
else
    echo "ECHEC : $erreur" >&2
    # Octets : rsync coupe en route ne donne pas ses chiffres, ceux des modules
    # precedents sont donc un minimum, pas le total.
    rendre_compte false "$erreur" "$duree" "$octets" "$inachevee"
    exit 1
fi
