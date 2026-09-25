# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Les adresses déjà utilisées sur un réseau, lues sur toutes les VM de l'hyperviseur.

OSIRIS ne connaissait que ses propres fiches : sur un réseau mutualisé où vivent
des dizaines de VM posées à la main, « déjà prises par OSIRIS » en listait une,
et choisir une adresse revenait à parier. Lecture seule.
"""
import pytest
from sqlmodel import Session

import main
from models import Hypervisor, engine

RESSOURCES = [
    {"vmid": 101, "node": "pve1", "type": "qemu", "status": "running"},
    {"vmid": 102, "node": "pve1", "type": "qemu", "status": "running"},
    {"vmid": 103, "node": "pve2", "type": "qemu", "status": "stopped"},
    {"vmid": 104, "node": "pve2", "type": "lxc", "status": "running"},
    {"vmid": 105, "node": "pve2", "type": "qemu", "status": "stopped"},
    {"vmid": 9000, "node": "pve1", "type": "qemu", "status": "stopped", "template": 1},
]
CONFIGS = {
    # Agent présent, et un Docker qui ne doit PAS compter
    101: {"name": "web-01", "net0": "virtio=02:00:00:00:01:01,bridge=vmbr320,firewall=1"},
    # Autre réseau : hors sujet
    102: {"name": "ailleurs", "net0": "virtio=02:00:00:00:01:02,bridge=vmbr12"},
    # Éteinte, adresse déclarée par cloud-init
    103: {"name": "cloud-01", "net0": "virtio=02:00:00:00:01:03,bridge=vmbr320",
          "ipconfig0": "ip=192.0.2.30/24,gw=192.0.2.1"},
    # Conteneur : l'adresse est dans la carte elle-même
    104: {"hostname": "ct-01", "net0": "name=eth0,bridge=vmbr320,hwaddr=02:00:00:00:01:04,ip=192.0.2.40/24"},
    # Éteinte, en DHCP : rien de connu
    105: {"name": "muette", "net0": "virtio=02:00:00:00:01:05,bridge=vmbr320", "ipconfig0": "ip=dhcp"},
}
AGENT_101 = {"result": [
    {"name": "eth0", "hardware-address": "02:00:00:00:01:01",
     "ip-addresses": [{"ip-address-type": "ipv4", "ip-address": "192.0.2.10"},
                      {"ip-address-type": "ipv6", "ip-address": "fe80::1"}]},
    {"name": "docker0", "hardware-address": "02:42:ac:11:00:01",
     "ip-addresses": [{"ip-address-type": "ipv4", "ip-address": "172.17.0.1"}]},
]}


@pytest.fixture
def hv_id(monkeypatch) -> int:
    async def fake_get(h, path):
        if path.endswith("cluster/resources?type=vm"):
            return RESSOURCES
        vmid = int(path.split("/")[6])
        if path.endswith("/config"):
            return CONFIGS[vmid]
        if path.endswith("/agent/network-get-interfaces"):
            if vmid == 101:
                return AGENT_101
            raise main.HTTPException(status_code=502, detail="QEMU guest agent is not running")
        return {}
    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    with Session(engine) as session:
        h = Hypervisor(name="pve", type="proxmox", url="https://pve.test:8006",
                       token_id="osiris@pve!osiris", token_secret="")
        session.add(h)
        session.commit()
        session.refresh(h)
        return h.id


def _usage(client, admin_headers, hv_id) -> dict:
    resp = client.get(f"/hypervisors/{hv_id}/network-usage", params={"bridge": "vmbr320"},
                      headers=admin_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_les_adresses_de_toutes_les_vm_du_reseau(client, admin_headers, hv_id):
    u = _usage(client, admin_headers, hv_id)
    assert [(a["ip"], a["vm"], a["source"]) for a in u["adresses"]] == [
        ("192.0.2.10", "web-01", "agent"),
        ("192.0.2.30", "cloud-01", "configuration"),
        ("192.0.2.40", "ct-01", "configuration"),
    ]


def test_seule_la_carte_branchee_sur_ce_reseau_compte(client, admin_headers, hv_id):
    """Le 172.17.0.1 d'un Docker n'est pas une adresse du réseau client."""
    ips = [a["ip"] for a in _usage(client, admin_headers, hv_id)["adresses"]]
    assert "172.17.0.1" not in ips and "fe80::1" not in ips


def test_une_vm_sans_adresse_connue_est_signalee(client, admin_headers, hv_id):
    """Inconnue ne veut pas dire libre : elle est listée, pas oubliée."""
    assert _usage(client, admin_headers, hv_id)["sans_adresse"] == ["muette"]


def test_les_gabarits_et_les_autres_reseaux_sont_ignores(client, admin_headers, hv_id):
    vms = {a["vm"] for a in _usage(client, admin_headers, hv_id)["adresses"]}
    assert "ailleurs" not in vms


@pytest.mark.parametrize("valeur, attendu", [
    ("ip=192.0.2.5/24,gw=192.0.2.1", "192.0.2.5"),
    ("ip=dhcp", ""),
    ("", ""),
    ("192.0.2.9/24", "192.0.2.9"),
])
def test_ip_declaree(valeur, attendu):
    assert main._ip_declaree(valeur) == attendu
