# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Proposer l'adressage d'un réseau, sans jamais inventer d'adresse.

Le formulaire de création réclamait adresse, passerelle et DNS sans rien proposer.
Or seule l'adresse appartient à la machine : la passerelle et le DNS sont des
propriétés du RÉSEAU, identiques pour toutes les VM qui y sont raccordées. Les
retaper de mémoire à chaque déploiement offre une prise à la faute de frappe là
où elle coûte le plus cher — une passerelle erronée ne fait échouer aucun appel :
la VM démarre, ne route nulle part, et reste « en attente » sans explication.

Deux sources, et une abstention assumée :

- le bridge lui-même, lu en direct — autoritaire, mais muet la plupart du temps ;
- les déploiements déjà faits sur ce réseau — la seule source qui reste sinon ;
- rien pour l'adresse IP : OSIRIS ne voit que ses propres fiches.
"""
import pytest
from sqlmodel import Session, select

import main
from models import Hypervisor, Machine, engine

# `vmbr12` porte une adresse : le nœud est lui-même sur ce VLAN. `vmbr320` non —
# il n'est que commuté, ce qui est le cas ordinaire d'un réseau de VM.
RESEAUX = [
    {"iface": "vmbr12", "type": "bridge", "address": "172.29.12.13",
     "cidr": "172.29.12.13/24", "gateway": "172.29.12.1", "active": 1,
     "comments": "mgmt web"},
    {"iface": "vmbr320", "type": "bridge", "address": None, "cidr": None,
     "gateway": None, "active": 1, "comments": "Clients_MUTU"},
    {"iface": "bond0", "type": "bond", "address": None, "cidr": None,
     "gateway": None, "active": 1, "comments": None},
]


@pytest.fixture
def hv_id() -> int:
    with Session(engine) as session:
        h = Hypervisor(name="pve", type="proxmox", url="https://pve.test:8006",
                       token_id="osiris@pve!osiris", token_secret="", pool="osiris")
        session.add(h)
        session.commit()
        session.refresh(h)
        return h.id


@pytest.fixture
def proxmox(monkeypatch):
    """L'API du nœud, y compris son DNS — délibérément jamais consulté."""
    vu: list[str] = []

    async def fake_get(h, path):
        vu.append(path)
        if path.endswith("/network"):
            return RESEAUX
        if path.endswith("/dns"):
            return {"search": "exemple.local", "dns1": "8.8.8.8"}
        return {}

    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    return vu


def _machine(hv_id, hostname, bridge, ip, gw="", dns="") -> None:
    with Session(engine) as session:
        session.add(Machine(
            mac=hostname.lower().replace("-", ""), hostname=hostname, client="Acme",
            os="ubuntu", status="deployed", hypervisor_id=hv_id, proxmox_vm_id=0,
            vm_bridge=bridge, ip_cidr=ip, gateway=gw, dns_servers=dns))
        session.commit()


def _defauts(client, admin_headers, hv_id, bridge, node="pve1") -> dict:
    resp = client.get(f"/hypervisors/{hv_id}/nodes/{node}/network-defaults",
                      params={"bridge": bridge}, headers=admin_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Le bridge parle quand il porte une adresse ───────────────────────────────

def test_un_bridge_adresse_donne_reseau_et_passerelle(client, admin_headers, hv_id, proxmox):
    d = _defauts(client, admin_headers, hv_id, "vmbr12")

    assert d["reseau"] == "172.29.12.0/24"
    assert d["prefixe"] == 24
    assert d["gateway"] == "172.29.12.1"


def test_la_provenance_accompagne_chaque_valeur(client, admin_headers, hv_id, proxmox):
    """Une proposition sans provenance est une affirmation : l'opérateur doit
    pouvoir la peser avant de la valider."""
    d = _defauts(client, admin_headers, hv_id, "vmbr12")

    assert d["origines"]["reseau"] == "bridge"
    assert d["origines"]["gateway"] == "bridge"


def test_le_libelle_du_vlan_est_expose(client, admin_headers, hv_id, proxmox):
    """« Clients_MUTU » est ce que l'exploitant a en tête ; « vmbr320 », non."""
    assert _defauts(client, admin_headers, hv_id, "vmbr320")["libelle"] == "Clients_MUTU"


# ── Le cas ordinaire : un bridge muet ────────────────────────────────────────

def test_un_bridge_sans_adresse_et_sans_passe_ne_propose_rien(client, admin_headers,
                                                              hv_id, proxmox):
    """Ne rien savoir doit se dire. Une valeur inventée serait pire que le vide :
    elle serait validée sans être relue."""
    d = _defauts(client, admin_headers, hv_id, "vmbr320")

    assert d["reseau"] == "" and d["prefixe"] == 0
    assert d["gateway"] == "" and d["dns_servers"] == ""
    assert d["origines"] == {}


def test_un_deploiement_passe_renseigne_le_bridge_muet(client, admin_headers,
                                                       hv_id, proxmox):
    """La seule source qui reste quand le nœud n'est pas sur le VLAN."""
    _machine(hv_id, "SRV-A", "vmbr320", "10.10.5.20/24", "10.10.5.1", "10.10.5.9")

    d = _defauts(client, admin_headers, hv_id, "vmbr320")

    assert d["reseau"] == "10.10.5.0/24"
    assert d["gateway"] == "10.10.5.1"
    assert d["dns_servers"] == "10.10.5.9"
    assert set(d["origines"].values()) == {"deploiement"}


def test_le_bridge_prime_sur_lhistorique(client, admin_headers, hv_id, proxmox):
    """Lu en direct, il ne peut pas être périmé — une fiche ancienne, si."""
    _machine(hv_id, "SRV-B", "vmbr12", "172.29.12.50/24", "172.29.12.254", "172.29.12.9")

    d = _defauts(client, admin_headers, hv_id, "vmbr12")

    assert d["gateway"] == "172.29.12.1", "la passerelle déclarée par le nœud"
    assert d["origines"]["gateway"] == "bridge"


def test_le_dns_ne_peut_venir_que_de_lhistorique(client, admin_headers, hv_id, proxmox):
    """Aucun hyperviseur ne sait quel résolveur une VM doit utiliser."""
    _machine(hv_id, "SRV-C", "vmbr12", "172.29.12.50/24", "172.29.12.1", "172.29.12.9")

    d = _defauts(client, admin_headers, hv_id, "vmbr12")

    assert d["dns_servers"] == "172.29.12.9"
    assert d["origines"]["dns_servers"] == "deploiement"


def test_la_fiche_la_plus_recente_gagne(client, admin_headers, hv_id, proxmox):
    """Une renumérotation du réseau ne doit pas être écrasée par l'ancien plan."""
    _machine(hv_id, "SRV-VIEUX", "vmbr320", "10.10.5.20/24", "10.10.5.1", "10.10.5.9")
    _machine(hv_id, "SRV-NEUF", "vmbr320", "10.10.5.21/24", "10.10.5.254", "10.10.5.8")

    d = _defauts(client, admin_headers, hv_id, "vmbr320")

    assert d["gateway"] == "10.10.5.254"
    assert d["dns_servers"] == "10.10.5.8"


# ── Ce qu'on refuse de faire ─────────────────────────────────────────────────

def test_aucune_adresse_ip_nest_proposee(client, admin_headers, hv_id, proxmox):
    """OSIRIS ignore tout des machines posées à la main : il ne peut affirmer
    qu'une adresse est libre, donc il n'en désigne aucune."""
    _machine(hv_id, "SRV-D", "vmbr12", "172.29.12.50/24", "172.29.12.1")

    d = _defauts(client, admin_headers, hv_id, "vmbr12")

    assert "ip_cidr" not in d and "adresse" not in d
    assert d["occupees"] == ["172.29.12.50"], "on dit ce qui est PRIS, pas ce qui est libre"


def test_le_dns_du_noeud_nest_jamais_consulte(client, admin_headers, hv_id, proxmox):
    """Le nœud a un résolveur, et c'est un piège : c'est couramment un DNS public,
    alors qu'une VM qui rejoint un domaine Active Directory a besoin des
    contrôleurs de ce domaine. Le proposer ferait échouer la jonction, avec la
    caution d'OSIRIS."""
    d = _defauts(client, admin_headers, hv_id, "vmbr320")

    assert d["dns_servers"] == ""
    assert not any(p.endswith("/dns") for p in proxmox), proxmox


# ── Le périmètre de l'historique ─────────────────────────────────────────────

def test_un_autre_bridge_ne_contamine_pas(client, admin_headers, hv_id, proxmox):
    """Deux réseaux du même cluster n'ont aucune raison de partager un plan
    d'adressage : mélanger les deux propose une passerelle d'un autre VLAN."""
    _machine(hv_id, "SRV-E", "vmbr12", "172.29.12.50/24", "172.29.12.1", "172.29.12.9")

    d = _defauts(client, admin_headers, hv_id, "vmbr320")

    assert d["gateway"] == "" and d["dns_servers"] == ""


def test_un_autre_hyperviseur_ne_contamine_pas(client, admin_headers, hv_id, proxmox):
    """Un nom de bridge n'a rien d'unique : « vmbr0 » existe sur tous les clusters."""
    with Session(engine) as session:
        autre = Hypervisor(name="autre", type="proxmox", url="https://x.test:8006",
                           token_id="a@pve!b", token_secret="")
        session.add(autre)
        session.commit()
        session.refresh(autre)
        autre_id = autre.id
    _machine(autre_id, "SRV-F", "vmbr320", "192.168.9.10/24", "192.168.9.1", "192.168.9.5")

    d = _defauts(client, admin_headers, hv_id, "vmbr320")

    assert d["gateway"] == "" and d["reseau"] == ""


def test_une_fiche_en_dhcp_est_ignoree(client, admin_headers, hv_id, proxmox):
    """Sans adresse, elle n'apprend rien sur le plan d'adressage du réseau."""
    _machine(hv_id, "SRV-G", "vmbr320", "", "", "")

    assert _defauts(client, admin_headers, hv_id, "vmbr320")["reseau"] == ""


def test_une_adresse_illisible_ne_fait_pas_tomber_la_route(client, admin_headers,
                                                           hv_id, proxmox):
    """Les fiches antérieures à la validation d'adressage peuvent contenir
    n'importe quoi : une seule ne doit pas priver le formulaire de toute aide."""
    _machine(hv_id, "SRV-CASSEE", "vmbr320", "pas-une-adresse", "10.10.5.1")
    _machine(hv_id, "SRV-SAINE", "vmbr320", "10.10.5.21/24", "10.10.5.254", "10.10.5.8")

    d = _defauts(client, admin_headers, hv_id, "vmbr320")

    assert d["reseau"] == "10.10.5.0/24"
    assert d["gateway"] == "10.10.5.254"


# ── Les cas d'erreur ─────────────────────────────────────────────────────────

def test_un_bridge_inexistant_est_annonce_clairement(client, admin_headers, hv_id, proxmox):
    resp = client.get(f"/hypervisors/{hv_id}/nodes/pve1/network-defaults",
                      params={"bridge": "vmbr999"}, headers=admin_headers)

    assert resp.status_code == 404, resp.text
    assert "vmbr999" in resp.json()["detail"]


def test_la_route_est_reservee_aux_administrateurs(client, hv_id, proxmox):
    resp = client.get(f"/hypervisors/{hv_id}/nodes/pve1/network-defaults",
                      params={"bridge": "vmbr12"})

    assert resp.status_code in (401, 403), resp.text


# ── Ce que le déploiement laisse derrière lui ────────────────────────────────

def test_le_bridge_choisi_est_enregistre_sur_la_fiche(client, admin_headers,
                                                      hv_id, monkeypatch):
    """Le maillon qui rend l'aide cumulative : sans lui, chaque déploiement
    repart de zéro et le formulaire ne saura jamais rien d'un réseau muet."""
    etat: dict = {"clone": False}

    async def fake_get(h, path):
        if "type=vm" in path:
            return [{"vmid": 9003, "name": "modele", "node": "pve1", "template": 1,
                     "status": "stopped", "maxcpu": 2, "maxmem": 2147483648}]
        if path.endswith("/cluster/nextid"):
            return "150"
        if path.endswith("/config"):
            if not etat["clone"]:
                raise main.HTTPException(status_code=502, detail="Proxmox 500: no such VM")
            return {"name": "srv-neuf", "scsi0": "ceph:vm-150-disk-0,size=8G",
                    "smbios1": "uuid=11111111-2222-3333-4444-555555555555"}
        if path.endswith("/storage"):
            return [{"storage": "ceph", "type": "rbd", "active": 1, "content": "images"}]
        return {}

    async def fake_post(h, path, data=None):
        if path.endswith("/clone"):
            etat["clone"] = True
        return "UPID:pve:task"

    async def rien(*a, **k):
        return {}

    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    monkeypatch.setattr(main, "_proxmox_post", fake_post)
    monkeypatch.setattr(main, "_proxmox_put", rien)
    monkeypatch.setattr(main, "_proxmox_request", rien)
    monkeypatch.setattr(main, "_proxmox_wait_task", rien)

    resp = client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": "srv-neuf", "client": "Acme", "os": "ubuntu", "node": "pve1",
        "storage": "ceph", "bridge": "vmbr320", "boot_mode": "template",
        "template_id": 9003, "ip_cidr": "10.10.5.30/24", "gateway": "10.10.5.1",
        "dns_servers": "10.10.5.9",
    })
    assert resp.status_code == 201, resp.text

    with Session(engine) as session:
        fiche = session.exec(select(Machine).where(Machine.hostname == "srv-neuf")).one()
    assert fiche.vm_bridge == "vmbr320"
