# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Les accès SSH du SITE : posés sur chaque VM Linux de l'hyperviseur.

Chaque site a son serveur d'administration (PXE, bastion) qui doit entrer sur
toutes les VM qui y tournent, quel que soit le profil choisi. Deux réglages sur
l'hyperviseur :
- des clés publiques chez ROOT, en clé uniquement — root n'a jamais de mot de passe ;
- un mot de passe SSH pour le compte d'administration du profil, et pour lui seul.

La configuration sshd est vérifiée avec `sshd -T`, pas en cherchant du texte :
un `Match` mal placé se lit très bien et ne fait rien.
"""
import re
import shutil
import subprocess

import pytest
from sqlmodel import Session

import main
from models import Hypervisor, engine

RSA = ("ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDsxyO8yzHmIbPQNeIbRLWM6ghD24jmwDefNEbbjIGHc/BwQk0z4dbgWTQC8sQ"
       "egHvaH9dliAmJgV97TAsIgtd72+SPpXKSIWSvCvlZEpE7RObp+h8KA3L93UrnvwTmjwmBpDlJvxkNiKpqM3xEFPlcc19i9V7u"
       "vCf/Hr3qO3cwVmMtll4/1UXsfp5tadsF0Jhk3J3IOpg9BjXD0w0hI25ow0TumHm97ekONtFI2bWx/olm5skWsCfL1iit4MnMDt"
       "L4hzTZAPVmldksUPBbCd26f+Vpj6695IKaUDDP+ZyiELgqIBpiDX0HlazfaVOIJWm3TEBcGivbsacNh4xqztNF root@bastion")
ED = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOJMLT5FY7PGlhMRilTN7PKYnQ1zZb6V0JHZJo0GGYcl pxe@site"

_PROFIL = {"os": "debian", "default_user": "humans", "join_domain": False, "machine_type": "server",
           "app_ids": "", "tv_suffix": "", "vm_data_disk_gb": 0, "set_root_password": True}


def _script(**hv):
    h = Hypervisor(name="site", url="https://pve.test:8006", **hv) if hv else None
    return main._firstboot_linux_content(
        hostname="srv-test", mac="aabbccddeeff", ou="", profile_ctx=dict(_PROFIL),
        linux_apps=[], zabbix=None, osiris_url="http://osiris.test", hyperviseur=h)


# ── API ───────────────────────────────────────────────────────────────────────

def _hv(client, admin_headers) -> int:
    r = client.post("/hypervisors", headers=admin_headers, json={
        "name": "nova", "url": "https://pve.test:8006", "tls_verify": False})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_les_cles_sont_normalisees_et_dedoublonnees(client, admin_headers):
    hv = _hv(client, admin_headers)
    r = client.patch(f"/hypervisors/{hv}", headers=admin_headers, json={
        "ssh_root_keys": f"  {RSA}  \n\n# commentaire\n{ED}\n{RSA}\n", "ssh_password_login": True})
    assert r.status_code == 200, r.text
    assert r.json()["ssh_root_keys"] == f"{RSA}\n{ED}"
    assert r.json()["ssh_password_login"] is True


@pytest.mark.parametrize("mauvaise", ["pas une clé", RSA[:-60] + " root@x", "SSHEOF"])
def test_une_ligne_qui_n_est_pas_une_cle_est_refusee(client, admin_headers, mauvaise):
    """La liste finit dans un script root : rien d'autre qu'une clé n'y entre."""
    hv = _hv(client, admin_headers)
    r = client.patch(f"/hypervisors/{hv}", headers=admin_headers, json={"ssh_root_keys": mauvaise})
    assert r.status_code == 422, r.text
    assert "ligne 1" in r.json()["detail"]


# ── Rendu ─────────────────────────────────────────────────────────────────────

def test_sans_reglage_du_site_rien_ne_change():
    contenu = _script()
    assert "Acces SSH du site" not in contenu
    assert "Mot de passe root de secours" in contenu


def test_le_script_reste_du_bash_valide():
    contenu = _script(ssh_root_keys=f"{RSA}\n{ED}", ssh_password_login=True)
    subprocess.run(["bash", "-n"], input=contenu, text=True, check=True)


def test_les_cles_vont_chez_root():
    contenu = _script(ssh_root_keys=f"{RSA}\n{ED}")
    assert RSA in contenu and ED in contenu
    assert "/root/.ssh/authorized_keys" in contenu


def test_root_ne_recoit_jamais_de_mot_de_passe_quand_le_site_en_donne_un():
    """Un seul mot de passe par fiche, et c'est celui du compte du profil."""
    contenu = _script(ssh_password_login=True)
    assert "Mot de passe root de secours" not in contenu
    assert "echo 'humans'\":$_mdp_site\" | chpasswd" in contenu


def test_le_bloc_passe_apres_le_durcissement_serveur():
    contenu = _script(ssh_root_keys=RSA)
    assert contenu.index("PermitRootLogin no") < contenu.index("Acces SSH du site")


# ── Effet réel sur sshd ───────────────────────────────────────────────────────

def _fragments(contenu: str) -> str:
    """Les lignes du rendu qui modifient sshd_config, telles quelles."""
    racine = re.search(r"^sed -i 's/\^#\*\[\[:space:\]\]\*PermitRootLogin.*?\n.*?\n", contenu, re.M | re.S)
    match = re.search(r"^    if ! grep -q '\^# OSIRIS acces du site'.*?^    fi\n", contenu, re.M | re.S)
    return (racine.group(0) if racine else "") + (match.group(0) if match else "")


@pytest.mark.skipif(not shutil.which("sshd") and not shutil.which("/usr/sbin/sshd"), reason="sshd absent")
def test_sshd_applique_root_par_cle_et_mot_de_passe_pour_humans_seul(tmp_path):
    sshd = shutil.which("sshd") or "/usr/sbin/sshd"
    cle_hote = tmp_path / "hote"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(cle_hote)], check=True)
    conf = tmp_path / "sshd_config"
    # Ce que laisse le durcissement serveur d'OSIRIS
    conf.write_text("PasswordAuthentication no\nPermitRootLogin no\nPubkeyAuthentication yes\n")
    fragment = _fragments(_script(ssh_root_keys=RSA, ssh_password_login=True))
    assert "PermitRootLogin" in fragment and "Match User" in fragment
    subprocess.run(["bash", "-ec", f'_sshd_conf="{conf}"\n{fragment}'], check=True)
    # Rejoué (redéploiement) : pas de second bloc Match
    subprocess.run(["bash", "-ec", f'_sshd_conf="{conf}"\n{fragment}'], check=True)
    assert conf.read_text().count("Match User") == 1

    def effectif(user):
        sortie = subprocess.run([sshd, "-T", "-f", str(conf), "-h", str(cle_hote),
                                 "-C", f"user={user},host=x,addr=192.0.2.1"],
                                capture_output=True, text=True, check=True).stdout
        return {l.split()[0]: l.split()[1] for l in sortie.splitlines() if " " in l}

    assert effectif("root")["permitrootlogin"] == "without-password"
    assert effectif("root")["passwordauthentication"] == "no"
    assert effectif("humans")["passwordauthentication"] == "yes"
    assert effectif("jdupont")["passwordauthentication"] == "no"


# ── Garde-fou avant création ──────────────────────────────────────────────────

@pytest.mark.refus_acces
def test_les_acces_du_site_comptent_comme_une_porte(monkeypatch):
    from types import SimpleNamespace
    from models import Profile
    profil = Profile(name="Sans clé", os="debian", default_user="humans", join_domain=False)
    monkeypatch.setattr(main, "_resolve_profile_for_vm", lambda body: profil)
    body = SimpleNamespace(os="debian")
    main._refuser_vm_sans_acces(body, Hypervisor(name="s", url="u", ssh_root_keys=RSA))
    main._refuser_vm_sans_acces(body, Hypervisor(name="s", url="u", ssh_password_login=True))
