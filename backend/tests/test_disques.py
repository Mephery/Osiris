# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Disques supplémentaires d'une VM Linux : validation, hyperviseur, premier démarrage.

Le premier démarrage lisait la taille du disque dans le PROFIL : un disque ajouté
au formulaire était créé et jamais formaté. La liste vit désormais sur la fiche.
La préparation des disques est EXÉCUTÉE ici, commandes simulées : c'est la seule
façon de prouver qu'elle retrouve le bon disque, ne touche jamais un disque
occupé, et fait échouer la machine quand un formatage échoue.
"""
import json
import stat
import subprocess

import pytest
from fastapi import HTTPException
from jinja2 import Environment, FileSystemLoader
from sqlmodel import Session, select

import main
from disques import config_proxmox, libelle_depuis_montage, valider_disques
from models import Machine, engine


# ── Validation ────────────────────────────────────────────────────────────────

def _d(**k):
    return {"taille_gb": 10, "point_montage": "/data", **k}


def test_le_libelle_est_propose_d_apres_le_point_de_montage():
    assert libelle_depuis_montage("/var/lib/mysql") == "mysql"
    assert valider_disques([_d(point_montage="/srv/Web.Data")])[0]["libelle"] == "web-data"


def test_l_ancien_champ_unique_devient_un_disque_data():
    assert valider_disques([], data_disk_gb=20) == [
        {"taille_gb": 20, "point_montage": "/data", "libelle": "data", "lvm": True, "systeme_fichiers": "ext4"}]
    assert valider_disques([], 0) == []


@pytest.mark.parametrize("disques, attendu", [
    ([_d(taille_gb=0)], "taille"),
    ([_d(point_montage="data")], "chemin absolu"),
    ([_d(point_montage="/srv/web data")], "chemin absolu"),   # un espace casserait le fstab
    ([_d(point_montage="/etc")], "répertoire du système"),
    ([_d(), _d(libelle="autre")], "déjà utilisé par un autre disque"),
    ([_d(libelle="Beaucoup-trop-long")], "1 à 12 caractères"),
    ([_d(), _d(point_montage="/srv/data")], "libellé « data » est déjà utilisé"),
    ([_d(systeme_fichiers="btrfs")], "ext4 ou xfs"),
    ([_d(point_montage=f"/d{i}") for i in range(5)], "Au plus 4"),
])
def test_une_liste_invalide_dit_quoi_corriger(disques, attendu):
    with pytest.raises(HTTPException) as err:
        valider_disques(disques)
    assert err.value.status_code == 422
    assert attendu in err.value.detail


def test_proxmox_recoit_chaque_disque_avec_son_libelle_en_numero_de_serie():
    disques = valider_disques([_d(), _d(point_montage="/var/lib/mysql", taille_gb=50)])
    assert config_proxmox(disques, "ceph") == {
        "scsi1": "ceph:10,serial=data", "scsi2": "ceph:50,serial=mysql"}


# ── La fiche fait foi pour le premier démarrage ──────────────────────────────

def test_le_premier_demarrage_lit_la_fiche_et_non_le_profil(client, test_machine, monkeypatch):
    """Profil sans disque, fiche avec deux : les deux sont préparés."""
    with Session(engine) as session:
        m = session.exec(select(Machine)).first()
        m.os = "debian"
        m.disques = json.dumps(valider_disques([_d(), _d(point_montage="/var/lib/mysql", systeme_fichiers="xfs")]))
        session.add(m)
        session.commit()
        mac = m.mac
    monkeypatch.setattr(main, "_exiger_fenetre_de_deploiement", lambda *a: None)
    script = client.get(f"/firstboot-ubuntu/{mac}").text
    assert "_preparer_disque 'data' 10 '/data' 1 'ext4'" in script
    assert "_preparer_disque 'mysql' 10 '/var/lib/mysql' 1 'xfs'" in script


# ── La préparation, exécutée ──────────────────────────────────────────────────

def _fonctions() -> str:
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    env.filters.setdefault("bash_squote", lambda v: "'" + str(v).replace("'", "'\\''") + "'")
    script = env.get_template("firstboot-ubuntu.sh.j2").render(
        machine={"hostname": "srv-01", "mac": "aabbccddeeff", "ou": "", "post_script": ""},
        profile={"machine_type": "server"}, linux_apps=[], zabbix=None,
        disques=valider_disques([_d()]), osiris_url="http://osiris.test", ip_attendue="")
    debut = script.index("_disques_pris=")
    return script[debut:script.index("\n_preparer_disque '", debut)]


# lsblk simulé : SERIAL, tailles, et disques « non vierges » pilotés par l'environnement
LSBLK = r'''#!/bin/bash
case "$*" in
  "-d -n -o NAME,SERIAL") printf '%b' "$SERIES" ;;
  "-d -n -b -o NAME,TYPE,RM,SIZE") printf '%b' "$TAILLES" ;;
  -no\ FSTYPE,PARTTYPE*) for n in $OCCUPES; do [ "${@: -1}" = "/dev/$n" ] && echo ext4; done ;;
  -no\ PKNAME*) echo sda ;;
  *) true ;;
esac
'''


def _executer(tmp_path, *, series="", tailles="", occupes="", mkfs_rc=0, disque=None,
              xfs_present=True) -> dict:
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    journal = tmp_path / "appels"
    faux = {
        "lsblk": LSBLK,
        "findmnt": "#!/bin/bash\necho /dev/sda1\n",
        "mountpoint": "#!/bin/bash\nexit 1\n",
        "blkid": "#!/bin/bash\necho uuid-1234\n",
        "systemctl": "#!/bin/bash\nexit 0\n",
        "apt-get": "#!/bin/bash\nexit 100\n",
    }
    for cmd in ("pvcreate", "vgcreate", "lvcreate", "mount"):
        faux[cmd] = f'#!/bin/bash\necho "{cmd} $*" >> {journal}\n'
    for fs in ("ext4", "xfs") if xfs_present else ("ext4",):
        faux[f"mkfs.{fs}"] = f'#!/bin/bash\necho "mkfs.{fs} $*" >> {journal}\nexit {mkfs_rc}\n'
    for nom, corps in faux.items():
        f = bin_ / nom
        f.write_text(corps)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    fstab, montage = tmp_path / "fstab", tmp_path / "data"
    fstab.write_text("")
    d = disque or {"libelle": "data", "taille": 10, "lvm": 1, "fs": "ext4"}
    script = f'''
_log() {{ echo "LOG $1"; }}
_osiris_log() {{ echo "OSIRIS $1"; }}
_on_error() {{ echo "ERREUR $2"; }}
{_fonctions().replace("/etc/fstab", str(fstab))}
_preparer_disque {d["libelle"]} {d["taille"]} {montage} {d["lvm"]} {d["fs"]} || true
'''
    r = subprocess.run(["bash", "-c", script], text=True, capture_output=True,
                       env={"PATH": f"{bin_}:/usr/bin:/bin", "SERIES": series,
                            "TAILLES": tailles, "OCCUPES": occupes})
    return {"sortie": r.stdout + r.stderr, "appels": journal.read_text() if journal.exists() else "",
            "fstab": fstab.read_text()}


GO = 1073741824


def test_le_disque_est_retrouve_par_son_numero_de_serie(tmp_path):
    """Proxmox : sdc porte le libellé, même si sdb est vierge et de la même taille."""
    r = _executer(tmp_path, series="sda \nsdb autre\nsdc data\n",
                  tailles=f"sda disk 0 {20*GO}\nsdb disk 0 {10*GO}\nsdc disk 0 {10*GO}\n")
    assert "pvcreate -q /dev/sdc" in r["appels"], r["sortie"]
    assert "vgcreate -q vg_data /dev/sdc" in r["appels"]
    assert "mkfs.ext4 -q -L data /dev/vg_data/data" in r["appels"]
    assert "uuid-1234" in r["fstab"] and "ext4 defaults,nofail" in r["fstab"]
    assert "ERREUR" not in r["sortie"]


def test_sans_numero_de_serie_la_taille_departage(tmp_path):
    """vSphere : pas de série ; le disque de 50 Go n'est pas celui de 10 Go."""
    r = _executer(tmp_path, tailles=f"sda disk 0 {20*GO}\nsdb disk 0 {50*GO}\nsdc disk 0 {10*GO}\nfd0 disk 1 4096\n")
    assert "pvcreate -q /dev/sdc" in r["appels"], r["sortie"]


def test_un_disque_occupe_n_est_jamais_touche(tmp_path):
    r = _executer(tmp_path, series="sdb data\n", tailles=f"sdb disk 0 {10*GO}\n", occupes="sdb")
    assert r["appels"] == "", "rien ne doit être formaté"
    assert "pas vierge" in r["sortie"] and "ERREUR" not in r["sortie"]


def test_un_disque_introuvable_avertit_sans_faire_echouer(tmp_path):
    r = _executer(tmp_path, tailles=f"sda disk 0 {20*GO}\n")
    assert "introuvable" in r["sortie"] and "ERREUR" not in r["sortie"]


def test_sans_lvm_le_systeme_de_fichiers_est_pose_sur_le_disque(tmp_path):
    r = _executer(tmp_path, series="sdb data\n", tailles=f"sdb disk 0 {10*GO}\n",
                  disque={"libelle": "data", "taille": 10, "lvm": 0, "fs": "ext4"})
    assert "pvcreate" not in r["appels"]
    assert "mkfs.ext4 -q -L data /dev/sdb" in r["appels"]


def test_un_formatage_rate_fait_echouer_la_machine(tmp_path):
    """Dans une fonction, le piège ERR ne se déclenche pas tout seul : l'échec doit
    être signalé explicitement, sinon la machine se déclarerait déployée."""
    r = _executer(tmp_path, series="sdb data\n", tailles=f"sdb disk 0 {10*GO}\n", mkfs_rc=1)
    assert "ERREUR mkfs.ext4" in r["sortie"]
    assert "mount" not in r["appels"]


def test_xfs_sans_xfsprogs_retombe_sur_ext4_en_le_disant(tmp_path):
    r = _executer(tmp_path, series="sdb data\n", tailles=f"sdb disk 0 {10*GO}\n",
                  disque={"libelle": "data", "taille": 10, "lvm": 0, "fs": "xfs"}, xfs_present=False)
    assert "mkfs.ext4 -q -L data /dev/sdb" in r["appels"], r["sortie"]
    assert "xfsprogs non installable" in r["sortie"]
    assert " ext4 defaults" in r["fstab"], "le fstab suit le système réellement posé"


def test_xfs_present_est_bien_utilise(tmp_path):
    r = _executer(tmp_path, series="sdb data\n", tailles=f"sdb disk 0 {10*GO}\n",
                  disque={"libelle": "data", "taille": 10, "lvm": 1, "fs": "xfs"})
    assert "mkfs.xfs -q -L data /dev/vg_data/data" in r["appels"], r["sortie"]
    assert " xfs defaults" in r["fstab"]
