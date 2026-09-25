# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Swap et LVM au premier démarrage Linux.

- Swap : un fichier de 2 Go, seulement si aucun swap n'est actif. JAMAIS fatal :
  le script tourne sous `trap ERR`, et une machine sans swap fonctionne — la
  faire passer en échec pour ça serait pire que le mal.
- /data en LVM, pour l'agrandir à chaud ; sans lvm2 (images cloud Debian, VLAN
  sans dépôts), retour à l'ext4 direct, dit dans le journal.

Le bloc swap est EXÉCUTÉ ici, avec des commandes simulées : c'est la seule
façon de prouver qu'aucun échec n'y déclenche le piège.
"""
import re
import stat
import subprocess

import pytest
from jinja2 import Environment, FileSystemLoader


def _rendu(data_disk_gb: int = 0) -> str:
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    env.filters.setdefault("bash_squote", lambda v: "'" + str(v).replace("'", "'\\''") + "'")
    return env.get_template("firstboot-ubuntu.sh.j2").render(
        machine={"hostname": "srv-01", "mac": "aabbccddeeff", "ou": "", "post_script": ""},
        profile={"machine_type": "server"}, linux_apps=[], zabbix=None,
        data_disk_gb=data_disk_gb, osiris_url="http://osiris.test", ip_attendue="")


def test_le_script_rendu_reste_du_bash_valide():
    for gb in (0, 10):
        r = subprocess.run(["bash", "-n"], input=_rendu(gb), text=True, capture_output=True)
        assert r.returncode == 0, r.stderr


def _bloc_swap() -> str:
    script = _rendu()
    debut = script.index("# ── Swap")
    fin = script.index("\nfi\n", script.index("fichier de swap impossible", debut)) + 4
    return script[debut:fin]


def _executer(tmp_path, *, swap_actif=False, libre_ko=50_000_000, swapon_ok=True) -> dict:
    """Rejoue le bloc swap sous le même piège ERR que le vrai script."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    faux = {
        "swapon": f'''[ "$1" = "--noheadings" ] && {{ {'echo /swap.img' if swap_actif else 'true'}; exit 0; }}
exit {0 if swapon_ok else 1}''',
        "df": f'echo Avail; echo {libre_ko}',
        "fallocate": 'touch "$3"',
        "mkswap": "exit 0",
    }
    for nom, corps in faux.items():
        f = bin_ / nom
        f.write_text("#!/bin/bash\n" + corps + "\n")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    fichier, fstab = tmp_path / "swapfile", tmp_path / "fstab"
    fstab.write_text("")
    bloc = _bloc_swap().replace("/swapfile", str(fichier)).replace("/etc/fstab", str(fstab))
    script = f'''
ECHEC=0
trap 'ECHEC=1' ERR
_log() {{ echo "LOG $1"; }}
_osiris_log() {{ echo "OSIRIS $1"; }}
{bloc}
echo "ECHEC=$ECHEC"
'''
    r = subprocess.run(["bash", "-c", script], text=True, capture_output=True,
                       env={"PATH": f"{bin_}:/usr/bin:/bin"})
    return {"sortie": r.stdout, "echec": "ECHEC=1" in r.stdout,
            "fichier": fichier.exists(), "fstab": fstab.read_text()}


def test_un_swap_deja_actif_n_est_pas_double(tmp_path):
    r = _executer(tmp_path, swap_actif=True)
    assert not r["fichier"] and r["fstab"] == "" and not r["echec"]


def test_le_fichier_de_swap_est_cree_et_persistant(tmp_path):
    r = _executer(tmp_path)
    assert r["fichier"] and "none swap sw" in r["fstab"] and not r["echec"]
    assert "2 Go actif" in r["sortie"]


def test_un_swap_impossible_n_est_JAMAIS_fatal(tmp_path):
    """swapon refuse (btrfs, conteneur…) : avertissement, fichier retiré, et
    surtout pas de piège déclenché."""
    r = _executer(tmp_path, swapon_ok=False)
    assert not r["echec"], r["sortie"]
    assert not r["fichier"] and r["fstab"] == ""
    assert "AVERTISSEMENT" in r["sortie"]


def test_un_disque_trop_plein_n_a_pas_de_swap(tmp_path):
    r = _executer(tmp_path, libre_ko=1_000_000)
    assert not r["fichier"] and not r["echec"]


def test_data_passe_par_lvm_avec_repli_dit():
    script = _rendu(10)
    assert "vgcreate -q vg_data" in script
    # Sans lvm2, repli sur l'ext4 direct — mais annoncé, jamais silencieux
    assert re.search(r'_log "AVERTISSEMENT : lvm2 absent', script)
    # Le formatage et le montage visent le volume LVM, pas le disque brut
    assert 'mkfs.ext4 -q -L osiris-data "$_data_dev"' in script
    assert 'blkid -s UUID -o value "$_data_dev"' in script


def test_le_swap_est_verifie_par_un_smoke_test():
    assert '_add_test "Swap"' in _rendu()


def test_un_echec_d_installation_de_lvm2_dit_pourquoi():
    """Vu le 25/09 : « lvm2 absent et non installable », et rien d'autre — sur
    une VM sans agent invité, la raison était perdue pour de bon."""
    script = _rendu(10)
    assert "DPkg::Lock::Timeout=120 lvm2" in script
    assert '_osiris_log "apt lvm2 :' in script
    assert "lvm2 > /dev/null" not in script
