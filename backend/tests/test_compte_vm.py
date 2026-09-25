# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Le compte d'une personne précise sur UNE VM Linux : nom, clé SSH obligatoire, sudo.

La clé est obligatoire parce que la connexion par mot de passe est désactivée :
un compte sans clé existerait sans que personne puisse y entrer. Le bloc de
création est EXÉCUTÉ ici, commandes simulées.
"""
import base64
import json
import stat
import struct
import subprocess

import pytest
from fastapi import HTTPException
from jinja2 import Environment, FileSystemLoader
from sqlmodel import Session, select

from comptes import CompteVm, valider_compte
from models import Machine, engine


def cle(type_: str = "ssh-ed25519", commentaire: str = "jdupont@poste") -> str:
    """Une clé publique bien formée : son type est aussi inscrit DANS son contenu."""
    corps = struct.pack(">I", len(type_)) + type_.encode() + struct.pack(">I", 32) + b"\x01" * 32
    return f"{type_} {base64.b64encode(corps).decode()} {commentaire}"


def _c(**k):
    return CompteVm(**{"nom": "jdupont", "cle_ssh": cle(), **k})


# ── Validation ────────────────────────────────────────────────────────────────

def test_un_compte_valide_est_normalise():
    assert valider_compte(_c(sudo=True)) == {"nom": "jdupont", "cle_ssh": cle(), "sudo": True}


def test_rien_de_saisi_veut_dire_pas_de_compte():
    assert valider_compte(None) is None
    assert valider_compte(CompteVm(nom=" ", cle_ssh="")) is None


def test_une_cle_collee_sur_plusieurs_lignes_est_recollee():
    morceaux = cle().split(" ")
    assert valider_compte(_c(cle_ssh=f"{morceaux[0]}\n{morceaux[1]}\n{morceaux[2]}"))["cle_ssh"] == cle()


@pytest.mark.parametrize("compte, profil, attendu", [
    (dict(nom="JDupont"), "", "minuscule"),
    (dict(nom="root"), "", "compte du système"),
    (dict(nom="systemd-network"), "", "compte du système"),
    (dict(nom="humans"), "humans", "compte d'administration du profil"),
    (dict(cle_ssh=""), "", "obligatoire"),
    (dict(cle_ssh="AAAAC3NzaC1lZDI1NTE5 jdupont"), "", "commencer par son type"),
    (dict(cle_ssh=cle()[:40]), "", "tronquée"),
    (dict(cle_ssh=cle().replace("ssh-ed25519", "ssh-rsa", 1)), "", "tronquée"),
])
def test_un_compte_invalide_dit_quoi_corriger(compte, profil, attendu):
    with pytest.raises(HTTPException) as err:
        valider_compte(_c(**compte), profil)
    assert err.value.status_code == 422
    assert attendu in err.value.detail


# ── Création de la VM ─────────────────────────────────────────────────────────

def test_le_compte_est_enregistre_sur_la_fiche(client, admin_headers, monkeypatch):
    from tests.test_create_vm import _make_hypervisor, _patch_proxmox
    hv_id = _make_hypervisor()
    _patch_proxmox(monkeypatch, {})
    resp = client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": "srv-dev", "client": "Acme", "os": "ubuntu", "node": "pve",
        "storage": "ceph", "boot_mode": "pxe",
        "compte": {"nom": "jdupont", "cle_ssh": cle(), "sudo": False},
    })
    assert resp.status_code == 201, resp.text
    with Session(engine) as session:
        fiche = session.exec(select(Machine).where(Machine.hostname == "srv-dev")).first()
    assert json.loads(fiche.compte) == {"nom": "jdupont", "cle_ssh": cle(), "sudo": False}


def test_le_compte_est_refuse_sous_windows(client, admin_headers, monkeypatch, tmp_path):
    from tests.test_create_vm import _iso_bidon, _make_hypervisor, _patch_proxmox
    hv_id = _make_hypervisor()
    _iso_bidon(tmp_path, monkeypatch)
    _patch_proxmox(monkeypatch, {})
    resp = client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": "SRV-WIN", "client": "Acme", "os": "windows", "node": "pve",
        "storage": "local-lvm", "boot_mode": "pxe",
        "compte": {"nom": "jdupont", "cle_ssh": cle()},
    })
    assert resp.status_code == 422 and "Linux" in resp.json()["detail"]


# ── Le premier démarrage, exécuté ─────────────────────────────────────────────

def _rendu(compte: dict) -> str:
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    env.filters.setdefault("bash_squote", lambda v: "'" + str(v).replace("'", "'\\''") + "'")
    return env.get_template("firstboot-ubuntu.sh.j2").render(
        machine={"hostname": "srv-01", "mac": "aabbccddeeff", "ou": "", "post_script": ""},
        profile={"machine_type": "server"}, linux_apps=[], zabbix=None, disques=[],
        compte=compte, osiris_url="http://osiris.test", ip_attendue="")


def _executer(tmp_path, compte: dict, *, uid_existant: int | None = None) -> dict:
    script = _rendu(compte)
    bloc = script[script.index("_compte="):script.index("\n{% endif %}") if "{% endif %}" in script else None]
    bloc = bloc[:bloc.index("\nfi\n") + 4]
    home, sudoers = tmp_path / "home", tmp_path / "sudoers.d"
    home.mkdir(); sudoers.mkdir()
    bin_ = tmp_path / "bin"; bin_.mkdir()
    journal = tmp_path / "appels"
    uid = "" if uid_existant is None else str(uid_existant)
    faux = {
        "id": f'#!/bin/bash\n[ -f {tmp_path}/cree ] && {{ echo 1001; exit 0; }}\n'
              + (f'echo {uid}; exit 0\n' if uid else 'exit 1\n'),
        "useradd": f'#!/bin/bash\necho "useradd $*" >> {journal}\ntouch {tmp_path}/cree\n',
        "getent": f'#!/bin/bash\necho "jdupont:x:1001:1001::{home}:/bin/bash"\n',
        "chown": f'#!/bin/bash\necho "chown $*" >> {journal}\n',
        "dpkg": "#!/bin/bash\nexit 0\n",
        "systemctl": "#!/bin/bash\nexit 0\n",
    }
    for nom, corps in faux.items():
        f = bin_ / nom
        f.write_text(corps)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    corps = f'''
_log() {{ echo "LOG $1"; }}
_on_error() {{ echo "ERREUR $2"; }}
{bloc.replace("/etc/sudoers.d", str(sudoers))}
'''
    r = subprocess.run(["bash", "-c", corps], text=True, capture_output=True,
                       env={"PATH": f"{bin_}:/usr/bin:/bin"})
    cles = home / ".ssh" / "authorized_keys"
    return {"sortie": r.stdout + r.stderr, "appels": journal.read_text() if journal.exists() else "",
            "cles": cles.read_text() if cles.exists() else None,
            "sudo": (sudoers / "osiris-compte").read_text() if (sudoers / "osiris-compte").exists() else None}


def test_le_compte_est_cree_avec_sa_cle(tmp_path):
    r = _executer(tmp_path, {"nom": "jdupont", "cle_ssh": cle(), "sudo": False})
    assert "useradd -m -s /bin/bash jdupont" in r["appels"], r["sortie"]
    assert r["cles"] == cle() + "\n"
    assert r["sudo"] is None
    assert "ERREUR" not in r["sortie"]


def test_sudo_sans_mot_de_passe_quand_il_est_demande(tmp_path):
    """Le compte n'a pas de mot de passe : un sudo qui en demanderait un serait inutilisable."""
    r = _executer(tmp_path, {"nom": "jdupont", "cle_ssh": cle(), "sudo": True})
    assert r["sudo"] == "jdupont ALL=(ALL) NOPASSWD:ALL\n"


def test_un_compte_systeme_de_l_image_n_est_jamais_ouvert(tmp_path):
    r = _executer(tmp_path, {"nom": "jdupont", "cle_ssh": cle(), "sudo": True}, uid_existant=110)
    assert r["cles"] is None and r["sudo"] is None and "useradd" not in r["appels"]
    assert "compte systeme" in r["sortie"]


def test_un_commentaire_de_cle_avec_apostrophe_reste_inoffensif(tmp_path):
    """La clé finit dans un script root : son commentaire ne doit rien pouvoir exécuter."""
    piege = cle(commentaire="l'ami'; touch /tmp/pirate; '")
    r = _executer(tmp_path, {"nom": "jdupont", "cle_ssh": piege, "sudo": False})
    assert r["cles"] == piege + "\n"
    assert "ERREUR" not in r["sortie"]


def test_le_compte_est_verifie_par_un_smoke_test():
    assert "_add_test 'Compte jdupont'" in _rendu({"nom": "jdupont", "cle_ssh": cle(), "sudo": False})
