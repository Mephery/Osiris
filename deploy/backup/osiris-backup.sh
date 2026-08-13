#!/usr/bin/env bash
# Sauvegarde de ce qui rend OSIRIS reconstructible : la base, les secrets, la
# configuration hors depot, et l'etat git reel de la machine.
#
# Ce script ne sauvegarde PAS /srv/data (WIM, ISO, pilotes) : ces dizaines de Go
# sont couvertes par la sauvegarde de la VM au niveau de l'hyperviseur, qui prend
# le disque entier. Les recopier ici chaque nuit couterait cher pour rien. Il en
# garde en revanche l'inventaire, pour savoir quoi retelecharger si l'on doit
# repartir de la seule archive.
#
#   osiris-backup.sh            sauvegarde puis purge selon la retention
#   osiris-backup.sh --verifier controle la derniere archive sans en creer
set -euo pipefail

DESTINATION=${DESTINATION:-/srv/backup}
RETENTION=${RETENTION:-14}          # nombre d'archives conservees
DEPOT=${DEPOT:-/opt/osiris}
BASE=${BASE:-osiris}

HORODATAGE=$(date +%Y%m%d-%H%M%S)
ARCHIVE="$DESTINATION/osiris-$HORODATAGE.tar.zst"

journal() { echo "$(date '+%H:%M:%S') $*"; }

verifier() {
    # Une sauvegarde jamais relue est une hypothese, pas une sauvegarde.
    local archive=${1:-$(ls -1t "$DESTINATION"/osiris-*.tar.zst 2>/dev/null | head -1)}
    [ -z "$archive" ] && { echo "aucune archive dans $DESTINATION" >&2; exit 1; }
    journal "verification de $(basename "$archive")"
    tar --zstd -tf "$archive" >/dev/null || { echo "archive illisible" >&2; exit 1; }
    # pg_restore --list echoue si le dump est tronque : c'est le seul controle
    # qui distingue un fichier present d'un fichier restaurable.
    local tmp; tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' RETURN
    tar --zstd -xf "$archive" -C "$tmp" --wildcards '*/base.dump'
    pg_restore --list "$tmp"/*/base.dump >/dev/null || {
        echo "le dump PostgreSQL n'est pas restaurable" >&2; exit 1; }
    journal "archive lisible et dump restaurable ($(du -h "$archive" | cut -f1))"
}

[ "${1:-}" = "--verifier" ] && { verifier; exit 0; }

install -d -m 700 "$DESTINATION"
TRAVAIL=$(mktemp -d)
trap 'rm -rf "$TRAVAIL"' EXIT
COFFRE="$TRAVAIL/osiris-$HORODATAGE"
mkdir -p "$COFFRE"/{config,depot}

journal "base de donnees"
# Format custom : restauration selective table par table, et compression integree.
sudo -u postgres pg_dump -Fc "$BASE" > "$COFFRE/base.dump"

journal "secrets et configuration"
# .env d'abord : sans FERNET_KEY, les colonnes chiffrees du dump (mots de passe de
# jonction AD, PIN BitLocker, secrets TOTP) sont definitivement illisibles.
cp "$DEPOT/backend/.env" "$COFFRE/config/backend.env"
cp -r /etc/dnsmasq.d "$COFFRE/config/" 2>/dev/null || true
cp /etc/caddy/Caddyfile "$COFFRE/config/" 2>/dev/null || true
cp /etc/systemd/system/osiris-*.service "$COFFRE/config/" 2>/dev/null || true
cp /etc/zabbix/zabbix_agent2.d/osiris.conf "$COFFRE/config/zabbix-osiris.conf" 2>/dev/null || true
cp /etc/sudoers.d/osiris-vpn "$COFFRE/config/" 2>/dev/null || true

journal "etat du depot"
# On developpe directement sur cette machine : ce qui n'est pas pousse n'existe
# nulle part ailleurs. Le bundle contient toutes les branches et tous les commits,
# le diff attrape ce qui n'est meme pas committe.
#
# safe.directory est indispensable : ce script tourne en root sur un depot qui
# appartient a l'utilisateur applicatif, et git refuse alors de l'ouvrir. On le
# declare a l'appel plutot que dans la config globale, pour n'ouvrir l'exception
# que le temps de la sauvegarde. A savoir : `git bundle` ne dit pas la vraie
# cause, il repond « Need a repository to create a bundle ».
depot_git() { git -C "$DEPOT" -c safe.directory="$DEPOT" "$@"; }

# Par defaut on n'embarque que ce qui n'est pas sur origin : quelques centaines
# de Ko, car le seul contenu irremplacable est celui qui n'existe nulle part
# ailleurs. L'histoire complete, elle, vit sur le depot distant ET dans la
# sauvegarde de la VM cote hyperviseur, qui prend le disque entier.
# BUNDLE_COMPLET=1 embarque tout et rend l'archive autonome, au prix de ~130 Mo
# par nuit — presque entierement les noyaux et initrd PXE suivis par git, des
# binaires qui ne changent jamais : ce serait 14 copies du meme bloc.
if [ "${BUNDLE_COMPLET:-0}" = "1" ]; then
    depot_git bundle create "$COFFRE/depot/depot.bundle" --all >/dev/null
else
    # `git bundle` refuse de creer un bundle vide : tout pousse n'est pas une
    # erreur, c'est le cas nominal. On le note et on continue.
    if ! depot_git bundle create "$COFFRE/depot/depot.bundle" \
            --branches --tags --not --remotes=origin >/dev/null 2>&1; then
        echo "tout est pousse sur origin : aucun commit local a embarquer" \
            > "$COFFRE/depot/depot.bundle.absent"
        depot_git remote get-url origin >> "$COFFRE/depot/depot.bundle.absent"
    fi
fi
depot_git rev-parse HEAD             > "$COFFRE/depot/HEAD"
depot_git status --porcelain         > "$COFFRE/depot/status.txt"
depot_git diff HEAD                  > "$COFFRE/depot/non-committe.patch"

journal "inventaire des donnees lourdes"
# Pas leur contenu : de quoi savoir ce qu'il manque et ou le retrouver.
find /srv/data -maxdepth 2 -type f -printf '%12s  %TY-%Tm-%Td  %p\n' 2>/dev/null \
    | sort -rn > "$COFFRE/inventaire-srv-data.txt"

cat > "$COFFRE/RESTAURATION.md" <<'FIN'
# Restaurer OSIRIS depuis cette archive

L'ordre compte : `.env` avant la base, sinon les colonnes chiffrees sont perdues.

1. **Secrets** — `config/backend.env` vers `backend/.env`, en **640**. La
   `FERNET_KEY` doit etre *celle-ci* : une autre cle ne dechiffrera pas les mots
   de passe de jonction AD, les PIN BitLocker ni les secrets TOTP du dump.
2. **Base** — `createdb osiris` puis
   `pg_restore -d osiris --clean --if-exists base.dump`.
3. **Code** — `git clone depot/depot.bundle osiris`, puis appliquer
   `depot/non-committe.patch` s'il n'est pas vide (developpement en cours au
   moment de la sauvegarde).
4. **Configuration** — les fichiers de `config/` vers `/etc/`, puis
   `systemctl daemon-reload` et redemarrage des services.
5. **Donnees lourdes** — non incluses. `inventaire-srv-data.txt` liste ce qui
   manque : les images Windows et les pilotes se retelechargent, mais la
   **golden image vient d'une machine de reference** et ne se retrouve que dans
   la sauvegarde de la VM cote hyperviseur.
FIN

journal "compression"
tar --zstd -cf "$ARCHIVE" -C "$TRAVAIL" "osiris-$HORODATAGE"
# L'archive contient .env en clair : elle vaut exactement ce que valent les
# secrets qu'elle transporte.
chmod 600 "$ARCHIVE"

verifier "$ARCHIVE"

journal "purge au-dela de $RETENTION archives"
ls -1t "$DESTINATION"/osiris-*.tar.zst 2>/dev/null | tail -n +$((RETENTION + 1)) \
    | while read -r vieille; do journal "  suppression $(basename "$vieille")"; rm -f "$vieille"; done

journal "termine : $ARCHIVE"
