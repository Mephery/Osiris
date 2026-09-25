# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Les réseaux proposés à une VM, et ceux qui ne le sont pas d'office.

La liste d'un nœud mêlait les réseaux des machines et ceux qui font tourner
l'hyperviseur (Ceph, sauvegarde, administration, PXE d'une autre équipe), plus
le bond, où aucune VM ne peut se brancher. Un nouveau venu y prenait le premier
nom rassurant, et une VM mal branchée ne fait échouer aucun appel : elle reste
muette. Le tri porte sur ce que fait le réseau, jamais sur une liste de noms.
"""
import pytest
from sqlmodel import Session

import main
from models import Hypervisor, engine

RESEAUX = [
    {"iface": "vmbr13", "type": "bridge", "address": "192.0.2.12",
     "cidr": "192.0.2.12/24", "comments": "Ceph ^"},
    {"iface": "vmbr320", "type": "bridge", "address": None, "cidr": None,
     "comments": "Clients_MUTU ^"},
    {"iface": "vmbr150", "type": "bridge", "address": None, "cidr": None,
     "comments": "Provisionning pxe"},
    {"iface": "bond0", "type": "bond", "address": None, "cidr": None, "comments": None},
]

STOCKAGES = [
    {"storage": "ceph_partage", "type": "rbd", "shared": 1, "active": 1,
     "content": "images,rootdir", "avail": 10 * 1073741824, "total": 20 * 1073741824},
    {"storage": "local-btrfs", "type": "btrfs", "shared": 0, "active": 1,
     "content": "images,iso", "avail": 30 * 1073741824, "total": 40 * 1073741824},
]


@pytest.fixture
def hv_id(monkeypatch) -> int:
    async def fake_get(h, path):
        if path.endswith("/network"):
            return RESEAUX
        if path.endswith("/storage"):
            return STOCKAGES
        return {}
    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    with Session(engine) as session:
        h = Hypervisor(name="pve", type="proxmox", url="https://pve.test:8006",
                       token_id="osiris@pve!osiris", token_secret="", pool="osiris")
        session.add(h)
        session.commit()
        session.refresh(h)
        return h.id


def _reseaux(client, admin_headers, hv_id) -> dict:
    resp = client.get(f"/hypervisors/{hv_id}/nodes/pve1/networks", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    return {n["iface"]: n for n in resp.json()}


def test_un_bond_n_est_jamais_propose(client, admin_headers, hv_id):
    """La carte d'une VM se branche sur un bridge : un bond ne peut qu'échouer."""
    assert "bond0" not in _reseaux(client, admin_headers, hv_id)


def test_un_bridge_ou_le_noeud_a_son_adresse_est_celui_de_l_hyperviseur(client, admin_headers, hv_id):
    assert _reseaux(client, admin_headers, hv_id)["vmbr13"]["reserve"] == "hyperviseur"


def test_un_reseau_d_amorcage_se_reconnait_a_son_libelle(client, admin_headers, hv_id):
    assert _reseaux(client, admin_headers, hv_id)["vmbr150"]["reserve"] == "pxe"


def test_un_reseau_de_machines_est_propose(client, admin_headers, hv_id):
    assert _reseaux(client, admin_headers, hv_id)["vmbr320"]["reserve"] == ""


def test_le_role_hyperviseur_prime_sur_le_libelle():
    """Un réseau où le nœud a son adresse reste « hyperviseur », même nommé PXE."""
    assert main._reserve_reseau({"iface": "vmbr9", "comments": "PXE", "hyperviseur": True}) == "hyperviseur"


def test_un_port_group_vmkernel_est_celui_de_l_hyperviseur():
    """Même règle côté vSphere : l'hyperviseur y a son adaptateur."""
    assert main._reserve_reseau({"iface": "vMotion", "comments": "port group distribué",
                                 "hyperviseur": True}) == "hyperviseur"
    assert main._reserve_reseau({"iface": "DATA-Infra", "comments": "port group distribué",
                                 "hyperviseur": False}) == ""


def test_le_stockage_dit_s_il_est_partage(client, admin_headers, hv_id):
    """Sans ce drapeau, le formulaire ne peut pas préférer le stockage qui laisse
    la VM changer de nœud."""
    resp = client.get(f"/hypervisors/{hv_id}/nodes/pve1/storages", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert {s["storage"]: s["shared"] for s in resp.json()} == {"ceph_partage": True, "local-btrfs": False}
