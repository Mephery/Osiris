# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Stockages d'un hyperviseur : savoir où l'on peut créer, et s'il reste de la place.

L'information manquait à l'encart « Tester », et elle ne pouvait PAS être prise
dans le tableau des nœuds : le `maxdisk` que Proxmox donne par nœud est la racine
de l'hyperviseur, pas l'endroit où atterrissent les VM. Sur Nova cette racine
annonce 446 Go quand le Ceph qui porte les disques en offre 17 To.

Deux pièges que ces tests verrouillent :

1. `cluster/resources` répond une ligne PAR NŒUD, même pour un stockage partagé —
   un Ceph apparaît donc quatre fois sur un cluster de quatre nœuds ;
2. les dépôts de sauvegarde ne sont pas des endroits où OSIRIS crée : les afficher
   noierait les deux lignes qui comptent vraiment.
"""
from sqlmodel import Session

import main
from models import Hypervisor, engine


def _hv() -> int:
    with Session(engine) as session:
        h = Hypervisor(name="pve", type="proxmox", url="https://pve.test:8006",
                       token_id="osiris@pve!osiris", token_secret="")
        session.add(h)
        session.commit()
        session.refresh(h)
        return h.id


# Extrait fidèle de ce que renvoie le cluster Nova (4 nœuds), y compris la
# répétition des stockages partagés et les dépôts de sauvegarde.
RESSOURCES_NOVA = [
    *[{"storage": "backup_pbs11", "node": n, "shared": 1, "status": "available",
       "content": "backup", "plugintype": "pbs",
       "disk": 22964113506304, "maxdisk": 25559775051776}
      for n in ("nvpx01", "nvpx02", "nvpx03", "nvpx04")],
    *[{"storage": "ceph_nova", "node": n, "shared": 1, "status": "available",
       "content": "rootdir,images", "plugintype": "rbd",
       "disk": 7850000000000, "maxdisk": 19030000000000}
      for n in ("nvpx01", "nvpx02", "nvpx03", "nvpx04")],
    *[{"storage": "local-btrfs", "node": n, "shared": 0, "status": "available",
       "content": "rootdir,images,backup,iso,vztmpl", "plugintype": "btrfs",
       "disk": 44000000000, "maxdisk": 483000000000}
      for n in ("nvpx01", "nvpx02", "nvpx03", "nvpx04")],
]


def _patch(monkeypatch, ressources=None):
    async def fake_get(h, path):
        if "type=storage" in path:
            return RESSOURCES_NOVA if ressources is None else ressources
        if path.endswith("/version"):
            return {"version": "9.2.3"}
        if path.endswith("/nodes"):
            return [{"node": "nvpx01", "status": "online", "cpu": 0.02,
                     "maxcpu": 112, "mem": 0, "maxmem": 0}]
        return {}
    monkeypatch.setattr(main, "_proxmox_get", fake_get)


def test_un_stockage_partage_napparait_quune_fois(client, admin_headers, monkeypatch):
    """Quatre lignes pour un Ceph laisseraient croire à quatre réserves distinctes."""
    hv_id = _hv()
    _patch(monkeypatch)

    st = client.post(f"/hypervisors/{hv_id}/test", headers=admin_headers).json()["storages"]

    ceph = [s for s in st if s["storage"] == "ceph_nova"]
    assert len(ceph) == 1, f"le Ceph partagé devait être replié, vu {len(ceph)} fois"
    assert ceph[0]["shared"] is True
    assert ceph[0]["node"] == "", "un stockage de cluster n'appartient à aucun nœud"


def test_un_stockage_local_apparait_par_noeud(client, admin_headers, monkeypatch):
    """L'inverse du précédent : `local-btrfs` est une réserve DIFFÉRENTE par nœud,
    et les replier cacherait qu'un seul nœud est plein."""
    hv_id = _hv()
    _patch(monkeypatch)

    st = client.post(f"/hypervisors/{hv_id}/test", headers=admin_headers).json()["storages"]

    locaux = [s for s in st if s["storage"] == "local-btrfs"]
    assert len(locaux) == 4, "un stockage local doit être listé pour chaque nœud"
    assert {s["node"] for s in locaux} == {"nvpx01", "nvpx02", "nvpx03", "nvpx04"}
    assert all(s["shared"] is False for s in locaux)


def test_les_depots_de_sauvegarde_sont_ecartes(client, admin_headers, monkeypatch):
    """OSIRIS ne crée rien sur un dépôt de sauvegarde : l'afficher noierait le reste."""
    hv_id = _hv()
    _patch(monkeypatch)

    st = client.post(f"/hypervisors/{hv_id}/test", headers=admin_headers).json()["storages"]

    assert not [s for s in st if "backup_pbs" in s["storage"]]
    assert {s["storage"] for s in st} == {"ceph_nova", "local-btrfs"}


def test_le_remplissage_est_calcule_sur_le_bon_champ(client, admin_headers, monkeypatch):
    """`disk` est l'espace UTILISÉ et `maxdisk` le total : confondre les deux
    afficherait un stockage vide comme plein."""
    hv_id = _hv()
    _patch(monkeypatch)

    st = client.post(f"/hypervisors/{hv_id}/test", headers=admin_headers).json()["storages"]
    ceph = next(s for s in st if s["storage"] == "ceph_nova")

    # Valeurs attendues DÉRIVÉES du jeu d'essai plutôt que recopiées : un nombre
    # magique recopié à la main documente l'erreur de calcul de son auteur.
    utilise, total = 7850000000000, 19030000000000
    Go = 1073741824
    assert ceph["total_gb"] == round(total / Go, 1)
    assert ceph["avail_gb"] == round((total - utilise) / Go, 1)
    assert ceph["used_pct"] == round(utilise / total * 100, 1)
    assert ceph["avail_gb"] < ceph["total_gb"], "libre ne peut pas dépasser le total"


def test_les_roles_disent_a_quoi_sert_le_stockage(client, admin_headers, monkeypatch):
    """`images` = disques de VM, `iso` = l'ISO WinPE. Le reste ne nous regarde pas."""
    hv_id = _hv()
    _patch(monkeypatch)

    st = client.post(f"/hypervisors/{hv_id}/test", headers=admin_headers).json()["storages"]

    assert next(s for s in st if s["storage"] == "ceph_nova")["roles"] == ["images"]
    assert next(s for s in st if s["storage"] == "local-btrfs")["roles"] == ["images", "iso"]


def test_un_stockage_hors_ligne_est_signale(client, admin_headers, monkeypatch):
    """Un stockage inaccessible fait échouer la création : il doit se voir avant."""
    hv_id = _hv()
    _patch(monkeypatch, ressources=[{
        "storage": "ceph_nova", "node": "nvpx01", "shared": 1, "status": "unknown",
        "content": "images", "plugintype": "rbd", "disk": 0, "maxdisk": 0,
    }])

    st = client.post(f"/hypervisors/{hv_id}/test", headers=admin_headers).json()["storages"]

    assert st[0]["online"] is False
    assert st[0]["used_pct"] == 0.0, "un stockage de taille nulle ne doit pas diviser par zéro"


def test_un_cluster_sans_stockage_utilisable_ne_casse_rien(client, admin_headers, monkeypatch):
    hv_id = _hv()
    _patch(monkeypatch, ressources=[])

    resp = client.post(f"/hypervisors/{hv_id}/test", headers=admin_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["storages"] == []
