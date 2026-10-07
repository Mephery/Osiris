# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Le compte de construction du gabarit ne survit pas au clonage.

Le gabarit Linux est construit et entretenu avec un compte sudo à mot de passe ;
chaque clone en héritait — le même compte, le même mot de passe, partout. Le
premier démarrage le supprime. Le bloc est EXÉCUTÉ, avec `id`/`userdel`/`pkill`
simulés : c'est le résultat qui compte, pas la présence d'une commande.
"""
import stat
import subprocess

import pytest
from jinja2 import Environment, FileSystemLoader

from comptes import COMPTE_GABARIT, valider_compte, CompteVm


def _rendu(default_user: str = "humans", compte_gabarit: str = COMPTE_GABARIT) -> str:
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    env.filters.setdefault("bash_squote", lambda v: "'" + str(v).replace("'", "'\\''") + "'")
    return env.get_template("firstboot-ubuntu.sh.j2").render(
        machine={"hostname": "srv-01", "mac": "aabbccddeeff", "ou": "", "post_script": ""},
        profile={"machine_type": "server", "default_user": default_user},
        linux_apps=[], zabbix=None, disques=[], osiris_url="http://osiris.test",
        ip_attendue="", partition_vg="osiris", root_gb=None, swap_gb=2,
        compte_gabarit=compte_gabarit)


def _bloc(script: str) -> str:
    debut = script.index("_gabarit=")
    fin = script.index("unset _gabarit") + len("unset _gabarit")
    return script[debut:fin]


def _executer(tmp_path, *, present=True, userdel_ok=True, default_user="humans") -> dict:
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    etat = tmp_path / "present"
    if present:
        etat.write_text("")
    faux = {
        # `id -u X` : vrai tant que le fichier témoin existe
        "id": f'[ -f "{etat}" ] && {{ echo 1000; exit 0; }}; exit 1',
        "userdel": (f'echo "userdel $*" >> "{tmp_path}/appels"; rm -f "{etat}"; '
                    'echo "mail spool not found" >&2; exit 0') if userdel_ok
                   else 'echo "user is currently used" >&2; exit 8',
        "pkill": f'echo "pkill $*" >> "{tmp_path}/appels"; exit 1',
    }
    for nom, corps in faux.items():
        f = bin_ / nom
        f.write_text("#!/bin/bash\n" + corps + "\n")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    script = f'''
ECHEC=0
trap 'ECHEC=1' ERR
_log() {{ echo "LOG $1"; }}
_osiris_log() {{ echo "OSIRIS $1"; }}
{_bloc(_rendu(default_user)).replace("/etc/sudoers.d", str(tmp_path))}
echo "ECHEC=$ECHEC"
'''
    r = subprocess.run(["bash", "-c", script], text=True, capture_output=True,
                       env={"PATH": f"{bin_}:/usr/bin:/bin"})
    appels = (tmp_path / "appels").read_text() if (tmp_path / "appels").exists() else ""
    return {"sortie": r.stdout, "echec": "ECHEC=1" in r.stdout,
            "present": etat.exists(), "appels": appels}


def test_le_script_rendu_reste_du_bash_valide():
    r = subprocess.run(["bash", "-n"], input=_rendu(), text=True, capture_output=True)
    assert r.returncode == 0, r.stderr


def test_le_compte_de_construction_est_supprime(tmp_path):
    r = _executer(tmp_path)
    assert not r["present"] and not r["echec"], r["sortie"]
    assert f"userdel -r {COMPTE_GABARIT}" in r["appels"]
    assert "supprime" in r["sortie"] and "AVERTISSEMENT" not in r["sortie"]


def test_un_echec_de_suppression_est_dit_jamais_tu(tmp_path):
    r = _executer(tmp_path, userdel_ok=False)
    assert r["present"] and not r["echec"], r["sortie"]
    assert "AVERTISSEMENT" in r["sortie"]
    assert f"OSIRIS compte {COMPTE_GABARIT}" in r["sortie"]   # remonte au journal OSIRIS


def test_sans_compte_de_construction_rien_ne_se_passe(tmp_path):
    r = _executer(tmp_path, present=False)
    assert r["appels"] == "" and r["sortie"].strip() == "ECHEC=0"


def test_jamais_le_compte_d_administration_du_profil(tmp_path):
    """Un profil qui aurait pris ce nom pour son compte d'administration : le
    supprimer fermerait la porte que le script vient d'ouvrir."""
    r = _executer(tmp_path, default_user=COMPTE_GABARIT)
    assert r["present"] and r["appels"] == ""


def test_le_preseed_et_le_firstboot_parlent_du_meme_compte():
    env = Environment(loader=FileSystemLoader("templates"), autoescape=False)
    preseed = env.get_template("preseed-gabarit-debian.cfg.j2").render(
        password_hash="x", compte_gabarit=COMPTE_GABARIT)
    assert f"d-i passwd/username string {COMPTE_GABARIT}" in preseed
    assert f"_gabarit='{COMPTE_GABARIT}'" in _rendu()


def test_aucune_personne_ne_peut_porter_ce_nom():
    with pytest.raises(Exception):
        valider_compte(CompteVm(nom=COMPTE_GABARIT,
                                cle_ssh="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"))
