# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""
Premier démarrage Linux : nom d'hôte, supervision Zabbix, crochet de
post-installation applicatif, et mécanisme d'amorçage générique.
"""
import pytest
from sqlmodel import Session as _BaseSession

from models import engine, Machine, Profile, Organization, Application


def Session(bind):
    return _BaseSession(bind, expire_on_commit=False)


@pytest.fixture
def linux_setup(clean_db):
    """Une organisation avec collecteur Zabbix, un profil Ubuntu, une machine supervisée."""
    with Session(engine) as session:
        org = Organization(name="Ferme IT", slug="ferme-it", zabbix_server="10.231.248.130")
        profile = Profile(name="Ubuntu test", os="ubuntu", join_domain=False)
        session.add(org)
        session.add(profile)
        session.commit()
        session.refresh(org)
        session.refresh(profile)
        machine = Machine(mac="0a0b0c0d0e0f", hostname="SRV-LINUX-01", client="Ferme IT",
                          os="ubuntu", profile_id=profile.id, organization_id=org.id)
        session.add(machine)
        session.commit()
        session.refresh(machine)
        return {"org": org, "profile": profile, "machine": machine}


def _firstboot(client, mac="0a0b0c0d0e0f"):
    res = client.get(f"/firstboot-linux/{mac}")
    assert res.status_code == 200
    return res.text


# ── Nom d'hôte ────────────────────────────────────────────────────────────────

def test_firstboot_pose_le_nom_dhote(client, linux_setup):
    """Sans ça, une VM clonée garde le nom du template et s'annonce ainsi au DHCP."""
    script = _firstboot(client)
    assert "hostnamectl set-hostname 'SRV-LINUX-01'" in script
    # \t littéral : c'est sed qui l'interprète sur la machine, pas Jinja ici
    assert r"127.0.1.1\tSRV-LINUX-01" in script


def test_firstboot_verrouille_le_nom_contre_cloud_init(client, linux_setup):
    """cloud-init repose le nom du datasource à chaque boot : il faut le neutraliser."""
    script = _firstboot(client)
    assert "preserve_hostname: true" in script
    assert "/etc/cloud/cloud.cfg.d/99-osiris-hostname.cfg" in script


def test_les_rappels_utilisent_la_mac_de_la_fiche(client, linux_setup):
    """La MAC est gravée à la génération, pas redéduite de la route par défaut."""
    script = _firstboot(client)
    assert '_osiris_mac="0a0b0c0d0e0f"' in script
    assert "ip route get 8.8.8.8" not in script


def test_firstboot_signale_la_fin_du_deploiement(client, linux_setup):
    """Sur le chemin cloud-init, c'est le SEUL signal de fin de déploiement."""
    script = _firstboot(client)
    assert "status?status=deployed" in script


# ── Supervision Zabbix ────────────────────────────────────────────────────────

def test_agent_zabbix_configure_en_mode_actif(client, linux_setup):
    script = _firstboot(client)
    assert "ServerActive=10.231.248.130" in script
    assert "Hostname=SRV-LINUX-01" in script
    # Métadonnée lue par l'auto-enregistrement côté Zabbix
    assert "HostMetadata=osiris linux ferme-it" in script


def test_smoke_test_verifie_le_flux_vers_le_collecteur(client, linux_setup):
    """Distingue « agent mal configuré » de « règle de pare-feu manquante »."""
    script = _firstboot(client)
    assert "/dev/tcp/10.231.248.130/10051" in script


def test_pas_dagent_si_machine_non_supervisee(client, linux_setup):
    with Session(engine) as session:
        machine = session.get(Machine, linux_setup["machine"].id)
        machine.supervised = False
        session.add(machine)
        session.commit()
    script = _firstboot(client)
    assert "zabbix" not in script.lower()


def test_pas_dagent_si_organisation_sans_collecteur(client, linux_setup):
    """Un agent sans adresse de collecteur serait muet : mieux vaut ne rien installer."""
    with Session(engine) as session:
        org = session.get(Organization, linux_setup["org"].id)
        org.zabbix_server = ""
        session.add(org)
        session.commit()
    script = _firstboot(client)
    assert "zabbix" not in script.lower()


def test_pas_dagent_si_machine_sans_organisation(client, linux_setup):
    with Session(engine) as session:
        machine = session.get(Machine, linux_setup["machine"].id)
        machine.organization_id = None
        session.add(machine)
        session.commit()
    script = _firstboot(client)
    assert "zabbix" not in script.lower()


def test_supervision_activee_par_defaut(client, admin_headers):
    res = client.post("/machines", headers=admin_headers, json={
        "mac": "112233445566", "hostname": "PC-NEUF", "client": "X", "os": "ubuntu",
    })
    assert res.status_code == 201
    assert res.json()["supervised"] is True


def test_supervision_desactivable_par_patch(client, admin_headers, linux_setup):
    res = client.patch("/machines/0a0b0c0d0e0f", headers=admin_headers,
                       json={"supervised": False})
    assert res.status_code == 200
    assert res.json()["supervised"] is False


def test_collecteur_zabbix_editable_par_organisation(client, admin_headers, linux_setup):
    res = client.patch(f"/organizations/{linux_setup['org'].id}", headers=admin_headers,
                       json={"zabbix_server": " 10.0.0.9 "})
    assert res.status_code == 200
    assert res.json()["zabbix_server"] == "10.0.0.9"


# ── Compte local et accès SSH ─────────────────────────────────────────────────

def test_compte_local_cree_sil_manque(client, linux_setup):
    """
    Une VM clonée d'un template n'a pas forcément le compte du profil. Sans lui
    elle est hermétique : ni SSH ni console.
    """
    with Session(engine) as session:
        profile = session.get(Profile, linux_setup["profile"].id)
        profile.default_user = "humans"
        session.add(profile)
        session.commit()
    script = _firstboot(client)
    assert "useradd -m -s /bin/bash 'humans'" in script
    assert "id -u 'humans'" in script       # créé seulement s'il manque
    assert "/etc/sudoers.d/osiris-default-user" in script


def test_cles_ssh_posees_meme_sur_un_poste_de_travail(client, linux_setup):
    """Le profil n'est pas 'server' ici : les clés doivent quand même être posées."""
    with Session(engine) as session:
        profile = session.get(Profile, linux_setup["profile"].id)
        profile.default_user = "humans"
        profile.ssh_authorized_keys = "ssh-ed25519 AAAAC3Nz coline@osiris"
        profile.machine_type = "workstation"
        session.add(profile)
        session.commit()
    script = _firstboot(client)
    assert "ssh-ed25519 AAAAC3Nz coline@osiris" in script
    assert "authorized_keys" in script
    # Une clé sans serveur SSH ne sert à rien
    assert "openssh-server" in script


# ── Crochet de post-installation Linux ────────────────────────────────────────

def test_script_de_post_installation_rendu_apres_le_paquet(client, linux_setup):
    with Session(engine) as session:
        app_obj = Application(name="Nginx test", apt_package="nginx",
                              linux_post_install="rm /etc/nginx/sites-enabled/default")
        session.add(app_obj)
        session.commit()
        session.refresh(app_obj)
        profile = session.get(Profile, linux_setup["profile"].id)
        profile.app_ids = str(app_obj.id)
        session.add(profile)
        session.commit()
    script = _firstboot(client)
    install_pos = script.index("apt-get install -y nginx")
    hook_pos = script.index("rm /etc/nginx/sites-enabled/default")
    assert install_pos < hook_pos


def test_crochet_editable_par_patch(client, admin_headers):
    created = client.post("/apps", headers=admin_headers,
                          json={"name": "Test app", "apt_package": "htop"}).json()
    res = client.patch(f"/apps/{created['id']}", headers=admin_headers,
                       json={"linux_post_install": "echo bonjour"})
    assert res.status_code == 200
    assert res.json()["linux_post_install"] == "echo bonjour"


# ── Amorçage générique ────────────────────────────────────────────────────────

def test_bootstrap_sert_un_script_sans_secret(client):
    """
    Le template ne doit contenir aucun identifiant : c'est la raison même pour
    laquelle cette voie a été retenue plutôt qu'un compte Proxmox dédié.
    """
    res = client.get("/bootstrap/linux")
    assert res.status_code == 200
    script = res.text
    assert "http://localhost:8000" in script
    assert "osiris-firstboot.service" in script
    # Les commentaires parlent de secrets, le code ne doit pas en contenir.
    code = "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))
    for marker in ("password", "token", "secret", "authorization"):
        assert marker not in code.lower()


def test_bootstrap_interroge_osiris_avec_la_mac_locale(client):
    script = client.get("/bootstrap/linux").text
    assert "/sys/class/net/" in script
    assert "/firstboot-linux/$mac" in script


def test_bootstrap_ne_desactive_pas_lunite_en_cas_dechec(client):
    """Une VM démarrée avant que sa fiche existe doit retenter au prochain boot."""
    script = client.get("/bootstrap/linux").text
    bootstrap_body = script[script.index("osiris-bootstrap.sh <<"):]
    assert "systemctl disable" not in bootstrap_body


def test_unite_systemd_sans_delai_de_demarrage(client):
    """Le délai oneshot par défaut (90 s) tuerait le firstboot en plein apt-get."""
    script = client.get("/bootstrap/linux").text
    assert "TimeoutStartSec=infinity" in script


def test_firstboot_linux_inconnu_renvoie_404(client, clean_db):
    assert client.get("/firstboot-linux/ffffffffffff").status_code == 404
