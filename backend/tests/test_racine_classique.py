# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""« / » d'un gabarit classique suit la taille du disque.

OSIRIS provisionne le disque plus grand que le gabarit ; on comptait sur le
module growpart de cloud-init pour l'étendre à « / ». Sur un clone nu vSphere,
cloud-init se désactive (aucune source de données) : disque de 20 Go, « / » à
8,7 Go, et aucun test pour le voir (07/10). Le premier démarrage agrandit donc
lui-même, et un smoke test mesure l'espace que « / » laisse inutilisé.

Les blocs sont EXÉCUTÉS, commandes disque simulées.
"""
import stat
import subprocess

from jinja2 import Environment, FileSystemLoader


def _rendu() -> str:
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    env.filters.setdefault("bash_squote", lambda v: "'" + str(v).replace("'", "'\\''") + "'")
    return env.get_template("firstboot-ubuntu.sh.j2").render(
        machine={"hostname": "srv-01", "mac": "aabbccddeeff", "ou": "", "post_script": ""},
        profile={"machine_type": "server"}, linux_apps=[], zabbix=None, disques=[],
        osiris_url="http://osiris.test", ip_attendue="", partition_vg="osiris",
        root_gb=None, swap_gb=2)


def _fonction() -> str:
    s = _rendu()
    debut = s.index("_agrandir_racine() {")
    return s[debut:s.index("\n}\n", debut) + 3] + "_agrandir_racine\n"


def _smoke() -> str:
    s = _rendu()
    debut = s.index("_racine_src=$(findmnt")
    return s[debut:s.index("\nfi\n", debut) + 4]


def _executer(tmp_path, bloc: str, *, src="/dev/sda1", fs="ext4",
              place=True, resize_ok=True) -> dict:
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    appels = tmp_path / "appels"
    faux = {
        "findmnt": f'[ "$2" = SOURCE ] && echo {src}; [ "$2" = FSTYPE ] && echo {fs}; exit 0',
        "lsblk": 'echo sda',
        # growpart : 0 = agrandi (ou agrandissable en --dry-run), 1 = NOCHANGE
        "growpart": f'echo "growpart $*" >> "{appels}"; exit {0 if place else 1}',
        "resize2fs": f'echo "resize2fs $*" >> "{appels}"; exit {0 if resize_ok else 1}',
        "xfs_growfs": f'echo "xfs_growfs $*" >> "{appels}"; exit 0',
        "df": 'echo Size; echo 19G',
    }
    for nom, corps in faux.items():
        f = bin_ / nom
        f.write_text("#!/bin/bash\n" + corps + "\n")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    script = f'''
ECHEC=0
trap 'ECHEC=1' ERR
_log() {{ echo "LOG $1"; }}
_add_test() {{ echo "TEST $1|$2|$3"; }}
{bloc}
echo "ECHEC=$ECHEC"
'''
    r = subprocess.run(["bash", "-c", script], text=True, capture_output=True,
                       env={"PATH": f"{bin_}:/usr/bin:/bin"})
    return {"sortie": r.stdout + r.stderr,
            "appels": appels.read_text() if appels.exists() else ""}


def test_le_script_rendu_reste_du_bash_valide():
    r = subprocess.run(["bash", "-n"], input=_rendu(), text=True, capture_output=True)
    assert r.returncode == 0, r.stderr


def test_la_branche_classique_agrandit_la_racine_en_premier():
    s = _rendu()
    corps = s[s.index("_partitionner_legacy() {"):]
    assert corps.index("_agrandir_racine") < corps.index("Swap : un FICHIER")


def test_ext4_partition_puis_systeme_de_fichiers(tmp_path):
    r = _executer(tmp_path, _fonction())
    assert "growpart /dev/sda 1" in r["appels"] and "resize2fs /dev/sda1" in r["appels"]
    assert "LOG / agrandie au disque : 19G" in r["sortie"] and "ECHEC=0" in r["sortie"]


def test_xfs_s_etend_par_son_point_de_montage(tmp_path):
    r = _executer(tmp_path, _fonction(), fs="xfs")
    assert "xfs_growfs /" in r["appels"] and "resize2fs" not in r["appels"]


def test_deja_a_la_taille_du_disque_rien_d_autre(tmp_path):
    r = _executer(tmp_path, _fonction(), place=False)
    assert "resize2fs" not in r["appels"]
    assert "deja a la taille du disque" in r["sortie"] and "ECHEC=0" in r["sortie"]


def test_un_systeme_de_fichiers_non_etendu_est_dit_jamais_fatal(tmp_path):
    r = _executer(tmp_path, _fonction(), resize_ok=False)
    assert "AVERTISSEMENT : partition agrandie mais systeme de fichiers ext4 non etendu" in r["sortie"]
    assert "ECHEC=0" in r["sortie"]


def test_une_racine_lvm_n_est_pas_touchee_ici(tmp_path):
    """La branche LVM a son propre agrandissement (PV puis LV)."""
    r = _executer(tmp_path, _fonction(), src="/dev/mapper/osiris-root")
    assert r["appels"] == "" and "pas une partition simple" in r["sortie"]


def test_le_smoke_test_voit_l_espace_inutilise(tmp_path):
    """Le cas du 07/10, qu'aucun test ne montrait."""
    r = _executer(tmp_path, _smoke(), place=True)
    assert "TEST Racine /|false|19G - le disque /dev/sda a de l'espace que / n'utilise pas" in r["sortie"]
    assert "growpart --dry-run /dev/sda 1" in r["appels"]


def test_le_smoke_test_reussit_quand_la_racine_occupe_le_disque(tmp_path):
    r = _executer(tmp_path, _smoke(), place=False)
    assert "TEST Racine /|true|19G" in r["sortie"]
