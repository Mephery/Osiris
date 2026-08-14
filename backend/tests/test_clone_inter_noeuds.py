# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Cloner un template vers le nœud demandé, où que vive le template.

Dans un cluster Proxmox, une VM a deux moitiés qui ne vivent pas au même endroit :
sa CONFIGURATION appartient à un nœud, son DISQUE est sur le stockage. Quand ce
stockage est partagé, le disque est lisible par tous les nœuds — seul le fichier
de configuration est ancré quelque part.

L'appel de clonage partait pourtant vers le nœud choisi dans le formulaire. Deux
conséquences : sur un template hébergé ailleurs, Proxmox répondait qu'il ne
connaissait pas cette VM ; et quand les deux coïncidaient, la VM naissait
forcément sur le nœud du modèle. Un template posé sur un nœud condamnait donc
tous ses déploiements à ce nœud-là, sur un cluster qui en compte quatre.
"""
import pytest
from sqlmodel import Session

import main
from models import Hypervisor, engine

# Le template vit sur « pve2 », l'opérateur déploie sur « pve1 ».
RESSOURCES = [
    {"vmid": 9003, "name": "ubuntu-osiris", "node": "pve2", "template": 1,
     "status": "stopped", "maxcpu": 2, "maxmem": 2147483648},
    {"vmid": 100, "name": "SRV-WIN", "node": "pve1", "template": 1,
     "status": "stopped", "maxcpu": 4, "maxmem": 4294967296},
    {"vmid": 110, "name": "une-vm-ordinaire", "node": "pve1", "template": 0,
     "status": "running", "maxcpu": 2, "maxmem": 2147483648},
]


def _hv() -> int:
    with Session(engine) as session:
        h = Hypervisor(name="pve", type="proxmox", url="https://pve.test:8006",
                       token_id="osiris@pve!osiris", token_secret="", pool="osiris")
        session.add(h)
        session.commit()
        session.refresh(h)
        return h.id


def _patch(monkeypatch) -> dict:
    vu: dict = {"clones": []}

    async def fake_get(h, path):
        if "type=vm" in path:
            return RESSOURCES
        if path.endswith("/cluster/nextid"):
            return "150"
        if path.endswith("/config"):
            # Le MÊME chemin sert deux fois, et doit répondre différemment : avant le
            # clone pour vérifier que l'identifiant est libre (donc échouer), après
            # pour relire la taille du disque (donc répondre). Un faux qui ignore
            # l'ordre ne peut pas satisfaire les deux.
            if not vu["clones"]:
                raise main.HTTPException(status_code=502,
                                         detail="Proxmox 500: no such VM")
            return {"name": "srv-neuf", "sata0": "ceph:vm-150-disk-0,size=8G",
                    "scsi0": "ceph:vm-150-disk-0,size=8G",
                    "smbios1": "uuid=11111111-2222-3333-4444-555555555555"}
        if path.endswith("/storage"):
            return [{"storage": "ceph", "type": "rbd", "active": 1, "content": "images"}]
        return {}

    async def fake_post(h, path, data=None):
        if path.endswith("/clone"):
            vu["clones"].append((path, data))
        return "UPID:pve:task"

    async def fake_wait(h, node, upid, max_wait=120):
        return None

    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    monkeypatch.setattr(main, "_proxmox_post", fake_post)
    monkeypatch.setattr(main, "_proxmox_put", lambda *a, **k: _rien())
    monkeypatch.setattr(main, "_proxmox_request", lambda *a, **k: _rien())
    monkeypatch.setattr(main, "_proxmox_wait_task", fake_wait)
    return vu


async def _rien():
    return {}


def _creer(client, admin_headers, hv_id, node, template_id):
    return client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": "srv-neuf", "client": "Acme", "os": "ubuntu",
        "node": node, "storage": "ceph", "bridge": "vmbr0",
        "boot_mode": "template", "template_id": template_id,
    })


# ── L'appel part vers le nœud du TEMPLATE ────────────────────────────────────

def test_le_clone_est_adresse_au_noeud_du_template(client, admin_headers, monkeypatch):
    """Adressé au nœud choisi, Proxmox répondait qu'il ne connaissait pas cette VM."""
    hv_id = _hv()
    vu = _patch(monkeypatch)

    resp = _creer(client, admin_headers, hv_id, node="pve1", template_id=9003)

    assert resp.status_code == 201, resp.text
    chemin, _ = vu["clones"][0]
    assert "/nodes/pve2/qemu/9003/clone" in chemin, \
        f"le clone doit viser le nœud du template, vu : {chemin}"


def test_la_vm_nait_sur_le_noeud_demande(client, admin_headers, monkeypatch):
    """C'est `target` qui libère le déploiement du nœud de son modèle."""
    hv_id = _hv()
    vu = _patch(monkeypatch)

    _creer(client, admin_headers, hv_id, node="pve1", template_id=9003)

    _, params = vu["clones"][0]
    assert params.get("target") == "pve1"


def test_sans_deplacement_on_ne_passe_pas_target(client, admin_headers, monkeypatch):
    """Passer `target` inutilement ferait échouer un cluster à un seul nœud, ou un
    template dont le disque est sur un stockage local."""
    hv_id = _hv()
    vu = _patch(monkeypatch)

    _creer(client, admin_headers, hv_id, node="pve1", template_id=100)

    chemin, params = vu["clones"][0]
    assert "/nodes/pve1/qemu/100/clone" in chemin
    assert "target" not in params


def test_le_pool_accompagne_toujours_le_clone(client, admin_headers, monkeypatch):
    """Acquis à ne pas perdre en refactorant : sans pool, la VM créée sort du
    périmètre où le jeton a le droit d'écrire."""
    hv_id = _hv()
    vu = _patch(monkeypatch)

    _creer(client, admin_headers, hv_id, node="pve1", template_id=9003)

    assert vu["clones"][0][1].get("pool") == "osiris"


def test_un_template_disparu_est_annonce_clairement(client, admin_headers, monkeypatch):
    """Le formulaire peut être resté ouvert pendant qu'on supprimait le template."""
    hv_id = _hv()
    _patch(monkeypatch)

    resp = _creer(client, admin_headers, hv_id, node="pve1", template_id=8888)

    assert resp.status_code == 404, resp.text
    assert "introuvable" in resp.json()["detail"]


# ── La liste des templates ───────────────────────────────────────────────────

def test_les_templates_sont_listes_pour_tout_le_cluster(client, admin_headers, monkeypatch):
    """Liés au nœud, ils enfermaient le formulaire : un template n'était proposé
    que si l'on avait deviné sur quel nœud il vivait."""
    hv_id = _hv()
    _patch(monkeypatch)

    t = client.get(f"/hypervisors/{hv_id}/templates", headers=admin_headers).json()

    assert {x["vmid"] for x in t} == {100, 9003}, "les deux templates, quel que soit le nœud"
    assert next(x for x in t if x["vmid"] == 9003)["node"] == "pve2", \
        "le nœud du template doit être exposé : c'est l'indice si le clone échoue"


def test_une_vm_ordinaire_nest_pas_proposee_comme_template(client, admin_headers, monkeypatch):
    hv_id = _hv()
    _patch(monkeypatch)

    t = client.get(f"/hypervisors/{hv_id}/templates", headers=admin_headers).json()

    assert 110 not in {x["vmid"] for x in t}
