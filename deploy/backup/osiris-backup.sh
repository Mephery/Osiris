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
#   osiris-backup.sh              sauvegarde puis purge selon la retention
#   osiris-backup.sh --verifier   controle la derniere archive sans en creer
#   osiris-backup.sh --repetition restaure la derniere archive pour de vrai,
#                                 dans une base jetable, et la detruit ensuite
set -euo pipefail

DESTINATION=${DESTINATION:-/srv/backup}
RETENTION=${RETENTION:-14}          # nombre d'archives conservees
DEPOT=${DEPOT:-/opt/osiris}
BASE=${BASE:-osiris}
GOLDEN=${GOLDEN:-/srv/data/windows/Golden_Image.wim}

# Reglages de la repetition de restauration (--repetition). La base jetable est
# creee, remplie, controlee, puis detruite : elle ne doit JAMAIS porter le nom
# de la base de production, d'ou le garde-fou au debut de repetition().
REPETITION_BASE=${REPETITION_BASE:-osiris_repetition}
TABLES_VITALES=${TABLES_VITALES:-"user organization hypervisor"}
PYTHON=${PYTHON:-$DEPOT/backend/venv/bin/python}

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

psql_repetition() { sudo -u postgres psql -d "$REPETITION_BASE" -tAc "$1"; }

# Volontairement globales : le trap EXIT s'execute une fois repetition() rendue,
# donc apres la disparition de ses variables locales. Les y avoir laissees
# faisait echouer le nettoyage sur un « variable sans liaison » et abandonnait
# derriere lui une base jetable pleine de vraies donnees.
REPETITION_TMP=""

nettoyer_repetition() {
    [ -n "$REPETITION_TMP" ] && rm -rf "$REPETITION_TMP"
    sudo -u postgres dropdb --if-exists "$REPETITION_BASE" >/dev/null 2>&1 || true
    return 0
}

repetition() {
    # `pg_restore --list` prouve qu'un dump n'est pas tronque, rien de plus : il
    # lit la table des matieres et s'arrete la. Une archive peut donc passer la
    # verification chaque nuit pendant des mois et ne pas remonter le jour ou on
    # en a besoin. La repetition, elle, restaure pour de vrai dans une base
    # jetable, controle ce qui en ressort, puis detruit la base.
    local archive=${1:-$(ls -1t "$DESTINATION"/osiris-*.tar.zst 2>/dev/null | head -1)}
    [ -z "$archive" ] && { echo "aucune archive dans $DESTINATION" >&2; exit 1; }
    if [ "$REPETITION_BASE" = "$BASE" ]; then
        echo "REPETITION_BASE vaut « $BASE » : la repetition detruirait la production" >&2
        exit 1
    fi

    journal "repetition de restauration depuis $(basename "$archive")"
    # Trap sur EXIT et non sur RETURN : les controles ci-dessous sortent en
    # erreur des qu'ils echouent, et un RETURN ne serait alors jamais joue —
    # on laisserait derriere nous une base jetable pleine de vraies donnees.
    REPETITION_TMP=$(mktemp -d)
    trap nettoyer_repetition EXIT
    local tmp=$REPETITION_TMP

    tar --zstd -xf "$archive" -C "$tmp" --wildcards '*/base.dump' '*/config/backend.env'

    # Base neuve a chaque fois : restaurer par-dessus les restes de la veille
    # reussirait meme avec un dump ampute de la moitie de ses tables.
    sudo -u postgres dropdb --if-exists "$REPETITION_BASE" >/dev/null 2>&1 || true
    sudo -u postgres createdb "$REPETITION_BASE"

    # --exit-on-error est le coeur du controle : par defaut pg_restore signale
    # ses erreurs et sort quand meme en 0, donc une restauration a moitie faite
    # passerait pour un succes. Le dump arrive par stdin parce qu'il est dans un
    # dossier que l'utilisateur postgres ne peut pas lire — et il contient toute
    # la base : l'ouvrir en lecture a tous, meme brievement, serait un prix
    # absurde pour economiser une redirection.
    if ! sudo -u postgres pg_restore --exit-on-error --no-owner --no-acl \
            -d "$REPETITION_BASE" < "$tmp"/*/base.dump; then
        echo "la restauration a echoue : cette archive ne remonte pas" >&2
        exit 1
    fi
    journal "  restauration acceptee sans une seule erreur"

    # Un schema a demi migre se restaure sans broncher, mais l'application le
    # refuse au demarrage : on veut savoir de quelle version on repartirait.
    local revision; revision=$(psql_repetition "select version_num from alembic_version")
    if [ -z "$revision" ]; then
        echo "alembic_version est vide : schema d'origine inconnu" >&2
        exit 1
    fi
    journal "  schema restaure en version $revision"

    # Un dump peut etre parfaitement valide ET vide. On exige donc du contenu la
    # ou il y en a forcement : sans utilisateur ni organisation, l'OSIRIS
    # restaure ne laisserait meme pas ouvrir une session.
    local vides=""
    for table in $TABLES_VITALES; do
        local lignes; lignes=$(psql_repetition "select count(*) from \"$table\"")
        journal "  $table : $lignes lignes"
        [ "$lignes" -eq 0 ] && vides="$vides $table"
    done
    if [ -n "$vides" ]; then
        echo "tables vitales vides apres restauration :$vides" >&2
        exit 1
    fi

    # Le controle qui manquait le plus. Les secrets sont chiffres en base, et la
    # cle vit dans .env : une archive dont les deux ne vont pas ensemble se
    # restaure parfaitement et ne rend que des secrets illisibles — jonction AD,
    # PIN BitLocker, jetons d'hyperviseur, tous a ressaisir a la main. Un seul
    # dechiffrement suffit a prouver que la paire est coherente.
    local env_archive; env_archive=$(ls "$tmp"/*/config/backend.env 2>/dev/null | head -1)
    local jeton; jeton=$(psql_repetition "select token_secret from hypervisor where token_secret <> '' limit 1")
    if [ -z "$env_archive" ]; then
        journal "  pas de backend.env dans l'archive : coherence des secrets non controlee"
    elif [ ! -x "$PYTHON" ]; then
        journal "  $PYTHON absent : coherence des secrets non controlee"
    elif [ -z "$jeton" ]; then
        journal "  aucun secret chiffre en base : rien a controler de ce cote"
    else
        local cle; cle=$(grep -m1 '^FERNET_KEY=' "$env_archive" | cut -d= -f2-)
        # Le clair n'est ni affiche ni conserve : on ne veut savoir que si la
        # cle l'ouvre.
        if ! FERNET_KEY="$cle" JETON="$jeton" "$PYTHON" -c 'import os
from cryptography.fernet import Fernet
Fernet(os.environ["FERNET_KEY"].encode()).decrypt(os.environ["JETON"].encode())' 2>/dev/null; then
            echo "la FERNET_KEY de l'archive ne dechiffre pas ses propres secrets :" \
                 "restaurable, mais tous les mots de passe seraient perdus" >&2
            exit 1
        fi
        journal "  la cle de l'archive dechiffre bien les secrets qu'elle accompagne"
    fi

    journal "repetition reussie : $(basename "$archive") remonte une base complete et lisible"
}

case "${1:-}" in
    --verifier)   verifier; exit 0 ;;
    --repetition) repetition "${2:-}"; exit 0 ;;
esac

# Si la destination est un volume dedie, il doit etre monte. Sans ce controle,
# un disque absent ferait ecrire les sauvegardes sur le disque systeme — donc
# sur celui qu'elles protegent — et personne ne s'en apercevrait avant le jour
# de la restauration. Le controle passe AVANT la creation du dossier, sinon on
# fabriquerait justement le point de montage manquant. EXIGER_MONTAGE=0 pour
# une destination volontairement posee sur le systeme de fichiers racine.
if [ "${EXIGER_MONTAGE:-1}" = "1" ] && ! mountpoint -q "$DESTINATION"; then
    echo "$DESTINATION n'est pas un point de montage : volume de sauvegarde absent" >&2
    exit 1
fi

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

journal "golden image"
# Seul fichier de /srv/data qui ne se retelecharge pas : il vient d'une machine
# de reference. Il ne change qu'a chaque nouvelle capture — quelques fois par an
# — donc on ne le recopie que si taille ou date ont bouge. Comparer les 14 Go a
# chaque nuit couterait des minutes de lecture pour rien.
if [ -f "$GOLDEN" ]; then
    install -d -m 700 "$DESTINATION/golden"
    signature=$(stat -c '%s:%Y' "$GOLDEN")
    marqueur="$DESTINATION/golden/.signature"
    copie="$DESTINATION/golden/$(basename "$GOLDEN")"
    if [ "$signature" = "$(cat "$marqueur" 2>/dev/null)" ] && [ -f "$copie" ]; then
        journal "  inchangee, rien a copier"
    else
        # Une capture ratee ecrase la golden image en place : si on ne gardait
        # que la derniere copie, on repliquerait l'image cassee par-dessus la
        # bonne. On decale donc l'ancienne avant d'ecrire la nouvelle.
        [ -f "$copie" ] && mv -f "$copie" "$DESTINATION/golden/precedente-$(basename "$GOLDEN")"
        journal "  copie de $(du -h "$GOLDEN" | cut -f1) en cours"
        # Fichier temporaire puis renommage : une copie interrompue ne doit
        # jamais ressembler a une copie valide.
        cp "$GOLDEN" "$copie.partiel" && mv "$copie.partiel" "$copie"
        echo "$signature" > "$marqueur"
        journal "  copiee"
    fi
else
    journal "  absente ($GOLDEN)"
fi

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
