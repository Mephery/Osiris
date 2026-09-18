# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Une VM où personne ne peut entrer est un échec, pas un succès.

Le 17/09, un profil serveur sans clé SSH ni mot de passe de secours a déployé
une VM hermétique : le durcissement coupe le mot de passe SSH, une VM ne reçoit
aucun mot de passe d'installation, et il n'y avait pas de domaine. OSIRIS a
écrit « Déploiement signalé comme réussi ».

Deux filets, parce qu'aucun ne suffit seul :
- AVANT : la création est refusée quand le profil ne prévoit aucune porte ;
- APRÈS : le premier démarrage compte les portes qui existent VRAIMENT sur la
  machine (le gabarit peut en apporter, une clé peut être mal collée) et passe
  la machine en échec s'il n'y en a aucune.

Le second est testé en EXÉCUTANT le fragment tel qu'il sort du rendu de
production, pas une copie : un test qui fabrique son propre script prouverait
que le code est juste, jamais qu'il est atteint.
"""
import re
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

import main
from models import Hypervisor, Machine, Profile, engine

# Tout le fichier : sans ce marqueur, conftest remplace le refus par une fonction
# vide, et les tests « ça passe » passeraient sans rien vérifier.
pytestmark = pytest.mark.refus_acces

CLE = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIexemple coline@poste"


def _profil(**kw) -> int:
    champs = dict(name="Serveur sans clé", os="debian", machine_type="server",
                  default_user="humans", join_domain=False)
    champs.update(kw)
    with Session(engine) as s:
        p = Profile(**champs)
        s.add(p)
        s.commit()
        s.refresh(p)
        return p.id


# ── Avant : le refus ──────────────────────────────────────────────────────────

def test_la_creation_est_refusee_AVANT_tout_appel_a_l_hyperviseur(
        client, admin_headers, monkeypatch):
    profil_id = _profil()
    with Session(engine) as s:
        h = Hypervisor(name="pve-test", url="https://pve.test:8006",
                       token_id="root@pam!osiris", token_secret="", tls_verify=False)
        s.add(h)
        s.commit()
        hv_id = h.id

    appels = []

    async def interdit(*a, **kw):
        appels.append(a)
        raise AssertionError("l'hyperviseur ne devait pas être appelé")
    monkeypatch.setattr(main, "_proxmox_get", interdit)
    monkeypatch.setattr(main, "_proxmox_post", interdit)

    r = client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": "srv-hermetique", "client": "Acme", "os": "debian", "profile_id": profil_id,
        "node": "pve", "storage": "local-lvm", "bridge": "vmbr0",
        "boot_mode": "template", "template_id": 9003,
    })
    assert r.status_code == 400, r.text
    assert "Serveur sans clé" in r.json()["detail"], "le message doit nommer le profil à corriger"
    assert not appels
    with Session(engine) as s:
        assert not s.exec(select(Machine)).all(), "aucune fiche ne doit naître d'un refus"


def _corps(profil_id=None, os="debian"):
    return SimpleNamespace(profile_id=profil_id, os=os)


def test_une_cle_suffit(clean_db):
    main._refuser_vm_sans_acces(_corps(_profil(ssh_authorized_keys=CLE)))


def test_le_root_de_secours_suffit(clean_db):
    main._refuser_vm_sans_acces(_corps(_profil(set_root_password=True)))


def test_une_vm_windows_n_est_jamais_refusee(clean_db):
    """L'administrateur intégré reçoit toujours un mot de passe gardé par OSIRIS."""
    main._refuser_vm_sans_acces(_corps(_profil(os="windows"), os="windows"))


def test_sans_aucun_profil_le_message_dit_d_en_creer_un(clean_db):
    with pytest.raises(HTTPException) as e:
        main._refuser_vm_sans_acces(_corps(None, os="debian"))
    assert "Aucun profil n'existe" in e.value.detail


# ── Après : le contrôle sur la machine ────────────────────────────────────────

@pytest.fixture(scope="module")
def script() -> str:
    return main._firstboot_linux_content(
        hostname="srv-acces", mac="aabbccddeeff", ou="",
        profile_ctx={"os": "debian", "default_user": "humans", "join_domain": False,
                     "app_ids": "", "tv_suffix": "", "vm_data_disk_gb": 0,
                     "machine_type": "server"},
        linux_apps=[], zabbix=None, osiris_url="http://osiris.test",
    )


def _fonction(script: str) -> str:
    m = re.search(r"^_portes_d_entree\(\) \{\n.*?^\}\n", script, re.S | re.M)
    assert m, "le contrôle d'accès n'est pas dans le script rendu"
    return m.group(0)


def _portes(tmp_path, script, *, cles="", mdp="humans L\nroot L", ssh_actif=True, domaine="",
            cles_root="", sshd="PermitRootLogin no\n"):
    """Exécute le contrôle contre de faux comptes : humans et root, rien d'autre."""
    (tmp_path / "sshd_config").write_text(sshd)
    racine = tmp_path / "root/.ssh"
    racine.mkdir(parents=True, exist_ok=True)
    (racine / "authorized_keys").write_text(cles_root)
    (tmp_path / "passwd").write_text(
        "root:x:0:0:root:/root:/bin/bash\n"
        "daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"
        "humans:x:1000:1000::/home/humans:/bin/bash\n")
    ssh = tmp_path / "home/humans/.ssh"
    ssh.mkdir(parents=True, exist_ok=True)
    (ssh / "authorized_keys").write_text(cles)
    etats = dict(l.split() for l in mdp.splitlines())
    faux = (
        f'systemctl() {{ {"return 0" if ssh_actif else "return 3"}; }}\n'
        'passwd() { case "$2" in '
        + "".join(f'{u}) echo "{u} {e} 2026-09-18";; ' for u, e in etats.items())
        + '*) echo "$2 L";; esac; }\n'
        f'realm() {{ printf "%s" "{domaine}"; }}\n'
    )
    r = subprocess.run(
        ["bash", "-c", faux + _fonction(script) + "_portes_d_entree"],
        capture_output=True, text=True, timeout=30,
        env={"PATH": "/usr/bin:/bin", "OSIRIS_PASSWD": str(tmp_path / "passwd"),
             "OSIRIS_HOME_RACINE": str(tmp_path), "OSIRIS_SSHD_CONFIG": str(tmp_path / "sshd_config")})
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_la_machine_du_17_09_n_a_aucune_porte(tmp_path, script):
    """Ni clé, humans sans mot de passe (L), root verrouillé, pas de domaine."""
    assert _portes(tmp_path, script) == ""


def test_une_cle_est_une_porte(tmp_path, script):
    assert _portes(tmp_path, script, cles=CLE + "\n") == " cle SSH (humans)"


def test_une_cle_sans_serveur_SSH_n_en_est_pas_une(tmp_path, script):
    assert _portes(tmp_path, script, cles=CLE, ssh_actif=False) == ""


def test_un_fichier_de_cles_fait_de_commentaires_n_ouvre_rien(tmp_path, script):
    assert _portes(tmp_path, script, cles="# a coller ici\n\n") == ""


def test_le_mot_de_passe_root_est_une_porte(tmp_path, script):
    """Le secours console, ou un compte hérité du gabarit avec son mot de passe."""
    assert _portes(tmp_path, script, mdp="humans L\nroot P") == " mot de passe (root)"


def test_un_domaine_joint_est_une_porte(tmp_path, script):
    assert "domaine" in _portes(tmp_path, script, domaine="corp.local")


def test_un_compte_sans_shell_n_est_pas_une_porte(tmp_path, script):
    """daemon a un mot de passe utilisable mais /usr/sbin/nologin."""
    assert _portes(tmp_path, script, mdp="humans L\nroot L\ndaemon P") == ""


def test_zero_porte_passe_la_machine_en_ECHEC(script):
    """Le verdict lui-même, extrait du rendu et exécuté : sans porte, le statut
    part en « failed » et la fin du script n'annoncera pas de succès."""
    m = re.search(r"^_acces=\$\(_portes_d_entree\)\n.*?^fi\n", script, re.S | re.M)
    assert m, "le verdict d'accès n'est pas dans le script rendu"
    faux = (
        '_portes_d_entree() { :; }\n'
        '_add_test() { echo "TEST $1 $2"; }\n'
        '_log() { :; }\n'
        'curl() { echo "CURL $*" >&2; }\n'
        '_osiris_failed=0; osiris_url=http://o; _osiris_mac=aa\n'
    )
    r = subprocess.run(["bash", "-c", faux + m.group(0) + 'echo "ECHEC=$_osiris_failed"'],
                       capture_output=True, text=True, timeout=30)
    assert "TEST Acces a la machine false" in r.stdout
    assert "status=failed" in r.stderr
    assert "ECHEC=1" in r.stdout


def test_la_cle_de_root_n_ouvre_rien_quand_root_est_interdit_en_SSH(tmp_path, script):
    """Vu sur la première vraie VM du 18/09 : « cle SSH (root) » comptée comme
    une porte, alors que le durcissement interdit root en SSH."""
    assert _portes(tmp_path, script, cles_root=CLE) == ""


def test_la_cle_de_root_compte_si_root_est_autorise(tmp_path, script):
    assert _portes(tmp_path, script, cles_root=CLE, sshd="") == " cle SSH (root)"


def test_la_cle_de_courtoisie_des_images_cloud_n_ouvre_rien(tmp_path, script):
    """Les images cloud posent une clé réduite à un message : elle se voit, elle n'ouvre rien."""
    courtoisie = ('no-port-forwarding,no-agent-forwarding,command="echo \'Please login as the user '
                  'debian rather than root.\';sleep 10" ' + CLE)
    assert _portes(tmp_path, script, cles=courtoisie) == ""
    assert _portes(tmp_path, script, cles=courtoisie + "\n" + CLE) == " cle SSH (humans)"
