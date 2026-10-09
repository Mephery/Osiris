# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""L'adresse d'une machine sur sa fiche, et d'où on la tient.

Trois sources, de la plus sûre à la moins sûre : lue en direct par l'hyperviseur
sur la carte de la fiche, vue par la machine elle-même au premier démarrage
(seule source en DHCP sans agent invité), saisie à la création. La fiche dit
laquelle : une IP déclarée présentée comme sûre enverrait chercher la machine
là où elle n'est peut-être pas.
"""
import subprocess

import pytest
from sqlmodel import Session, select

import main
from models import Hypervisor, Machine, Profile, engine

MAC = "aabbcc000010"


def _machine(**kw) -> None:
    with Session(engine) as s:
        p = Profile(name="p", os="debian", default_user="humans")
        h = Hypervisor(name="nova", url="https://pve.test:8006")
        s.add_all([p, h])
        s.commit()
        champs = dict(mac=MAC, client="Acme", os="debian", hostname="vm-ip", profile_id=p.id,
                      hypervisor_id=h.id, proxmox_vm_id=123, proxmox_node="pve")
        champs.update(kw)
        s.add(Machine(**champs))
        s.commit()


def _lecture(monkeypatch, ips=None, erreur=False):
    async def lire(h, node, vm_id, mac):
        assert mac == MAC, "le filtre doit porter sur la MAC de la fiche"
        if erreur:
            raise RuntimeError("pas d'agent invité")
        return ips or []
    monkeypatch.setattr(main.ProxmoxProvider, "adresses_de_la_carte", staticmethod(lire))


def test_l_adresse_lue_en_direct_l_emporte(client, admin_headers, monkeypatch):
    _machine(ip_cidr="192.0.2.50/24", ip_constatee="192.0.2.99")
    _lecture(monkeypatch, ["192.0.2.77"])
    r = client.get(f"/machines/{MAC}/adresse", headers=admin_headers).json()
    assert (r["ip"], r["source"], r["compte"]) == ("192.0.2.77", "constatee", "humans")


def test_parmi_plusieurs_adresses_la_declaree_est_preferee_si_portee(client, admin_headers, monkeypatch):
    _machine(ip_cidr="192.0.2.50/24")
    _lecture(monkeypatch, ["192.0.2.77", "192.0.2.50"])
    r = client.get(f"/machines/{MAC}/adresse", headers=admin_headers).json()
    assert r["ip"] == "192.0.2.50" and r["ips"] == ["192.0.2.77", "192.0.2.50"]


def test_sans_agent_on_retombe_sur_l_adresse_remontee(client, admin_headers, monkeypatch):
    _machine(ip_cidr="192.0.2.50/24")
    _lecture(monkeypatch, erreur=True)
    client.post(f"/machines/{MAC}/smoke-tests", json={"tests": [], "ip": "192.0.2.61"})
    r = client.get(f"/machines/{MAC}/adresse", headers=admin_headers).json()
    assert (r["ip"], r["source"]) == ("192.0.2.61", "remontee")
    assert r["le"]


def test_a_defaut_l_adresse_saisie_marquee_declaree(client, admin_headers, monkeypatch):
    _machine(ip_cidr="192.0.2.50/24")
    _lecture(monkeypatch, [])
    r = client.get(f"/machines/{MAC}/adresse", headers=admin_headers).json()
    assert (r["ip"], r["source"]) == ("192.0.2.50", "declaree")


def test_rien_de_connu(client, admin_headers, monkeypatch):
    _machine()
    _lecture(monkeypatch, [])
    r = client.get(f"/machines/{MAC}/adresse", headers=admin_headers).json()
    assert (r["ip"], r["source"]) == ("", "")


def test_une_machine_physique_ne_questionne_aucun_hyperviseur(client, admin_headers, monkeypatch):
    _machine(hypervisor_id=None, proxmox_vm_id=0)
    _lecture(monkeypatch, erreur=True)
    client.post(f"/machines/{MAC}/smoke-tests", json={"tests": [], "ip": "192.0.2.62"})
    assert client.get(f"/machines/{MAC}/adresse", headers=admin_headers).json()["source"] == "remontee"


@pytest.mark.parametrize("ip", ["", "pas-une-ip", "127.0.0.1", "169.254.1.1", "0.0.0.0", "192.0.2.1; rm -rf /"])
def test_une_adresse_remontee_inutilisable_est_ignoree(client, ip):
    _machine()
    r = client.post(f"/machines/{MAC}/smoke-tests", json={"tests": [], "ip": ip})
    assert r.status_code == 200
    with Session(engine) as s:
        assert s.exec(select(Machine)).first().ip_constatee == ""


def test_le_premier_demarrage_remonte_son_adresse():
    script = main._firstboot_linux_content(
        hostname="srv-test", mac=MAC, ou="",
        profile_ctx={"os": "debian", "default_user": "humans", "join_domain": False,
                     "app_ids": "", "tv_suffix": "", "vm_data_disk_gb": 0},
        linux_apps=[], zabbix=None, osiris_url="http://osiris.test")
    subprocess.run(["bash", "-n"], input=script, text=True, check=True)
    ligne = next(l for l in script.splitlines() if l.startswith("_ip_principale="))
    # Le calcul tel qu'il sort du rendu, sur une sortie de `ip route get` réelle
    faux_ip = ('ip() { echo "1.1.1.1 via 192.0.2.1 dev ens18 src 192.0.2.44 uid 0"; '
               'echo "    cache"; }\n')
    sortie = subprocess.run(["bash", "-c", faux_ip + ligne + '\necho "$_ip_principale"'],
                            capture_output=True, text=True, check=True).stdout.strip()
    assert sortie == "192.0.2.44"
    assert '\\"ip\\":\\"${_ip_principale}\\"' in script
