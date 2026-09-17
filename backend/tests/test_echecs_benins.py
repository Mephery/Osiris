# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Un déploiement réussi était déclaré en échec par deux commandes bénignes.

Le script de premier démarrage pose un `trap ... ERR` : toute commande NON
TESTÉE qui renvoie non-zéro marque la machine en échec côté OSIRIS, et c'est
définitif. C'est le bon réflexe — mais il exige que chaque commande dont
l'échec est normal soit explicitement traitée.

Deux ne l'étaient pas, et toutes deux échouent d'autant plus sûrement que le
reste est bien fait :

- `mount /data` renvoie non-zéro quand le point est DÉJÀ monté. Or un gabarit
  correct porte l'entrée fstab et son disque, donc systemd monte /data avant
  même que ce script ne tourne. Plus le gabarit est complet, plus le
  déploiement échouait.
- `apt-get update` renvoie non-zéro quand les dépôts sont injoignables. Un VLAN
  serveur qui ne sort pas est la norme, pas une panne — et l'installation qui
  suit sait déjà se débrouiller sans.

Constaté le 17/09 sur le premier clone d'un gabarit fraîchement construit :
tous les smoke tests au vert, et « la machine reste en échec côté OSIRIS ».
"""
import re
import subprocess

import pytest
from jinja2 import Environment, FileSystemLoader

GABARIT = "templates/firstboot-ubuntu.sh.j2"


@pytest.fixture(scope="module")
def source() -> str:
    return open(GABARIT, encoding="utf-8").read()


def test_aucun_apt_update_nu(source):
    """Nue, la commande fait tomber tout le déploiement dès que la machine ne
    sort pas — ce qui est le cas de conception sur les VLAN serveurs."""
    nus = re.findall(r"^apt-get update[^|\n]*$", source, re.M)
    assert not nus, f"apt-get update sans repli : {nus}"


def test_le_montage_verifie_avant_de_monter(source):
    assert "mountpoint -q /data" in source


def test_l_echec_de_depots_est_DIT(source):
    """Non fatal ne veut pas dire silencieux : si les paquets manquent ensuite,
    on doit pouvoir relier les deux dans le journal."""
    assert "depots injoignables" in source


# ── Le piège lui-même, exécuté ────────────────────────────────────────────────

def _piege(tmp_path, corps: str) -> str:
    """Rejoue la mécanique du trap ERR autour d'un fragment de script."""
    script = tmp_path / "t.sh"
    script.write_text(
        '_echecs=0\n'
        '_on_error() { echo "ECHEC ligne $1 : $2"; _echecs=1; }\n'
        'trap \'_on_error $LINENO "$BASH_COMMAND"\' ERR\n'
        '_log() { echo "LOG $1"; }\n'
        f'{corps}\n'
        'echo "ECHECS=$_echecs"\n')
    r = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=30)
    return r.stdout + r.stderr


def test_une_commande_nue_qui_echoue_DECLENCHE_le_piege(tmp_path):
    """Contrôle du contrôle : sans ça, les deux tests suivants passeraient même
    si le piège ne fonctionnait plus du tout."""
    sortie = _piege(tmp_path, "false")
    assert "ECHECS=1" in sortie


def test_un_montage_deja_fait_ne_declenche_RIEN(tmp_path):
    """La forme corrigée : on regarde avant d'agir."""
    sortie = _piege(tmp_path, 'mountpoint() { return 0; }\n'
                              'if mountpoint -q /data; then _log "deja monte"; '
                              'else mount /data; _log "monte"; fi')
    assert "ECHECS=0" in sortie
    assert "LOG deja monte" in sortie


def test_des_depots_injoignables_ne_declenchent_RIEN(tmp_path):
    """La forme corrigée : l'échec est absorbé et nommé."""
    sortie = _piege(tmp_path, 'apt-get() { return 100; }\n'
                              'apt-get update -qq || _log "AVERTISSEMENT : depots injoignables"')
    assert "ECHECS=0" in sortie
    assert "depots injoignables" in sortie


def test_le_piege_reste_actif_pour_le_RESTE(tmp_path):
    """On absorbe deux échecs connus, pas la vigilance : une vraie panne doit
    toujours faire échouer le déploiement."""
    sortie = _piege(tmp_path,
                    'apt-get() { return 100; }\n'
                    'apt-get update -qq || _log "AVERTISSEMENT : depots injoignables"\n'
                    'commande-qui-nexiste-pas 2>/dev/null')
    assert "ECHECS=1" in sortie
