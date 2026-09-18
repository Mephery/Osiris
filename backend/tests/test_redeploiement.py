# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Redéployer : un seul chemin, qui fait les choses justes.

Il y avait deux boutons presque identiques. L'un passait par la route de lot /
de statut, qui ne renvoyait PAS une VM Windows sur son CD WinPE : elle
redémarrait sur le Windows déjà installé et restait « en attente » pour
toujours. L'autre envoyait en plus un paquet Wake-on-LAN vers une adresse de
diffusion écrite en dur, qui ne correspondait à aucun réseau d'OSIRIS — il ne
réveillait rien, et l'écran annonçait « WoL envoyé ». Le WoL est retiré.
"""
from sqlmodel import Session

import main
from models import Machine, engine

MAC = "aabbccddee30"


def _machine():
    with Session(engine) as s:
        s.add(Machine(mac=MAC, hostname="PC-30", client="c", os="windows", status="deployed"))
        s.commit()


def _espion(monkeypatch):
    appels = []

    async def orienter(mac, vers_winpe):
        appels.append((mac, vers_winpe))
    monkeypatch.setattr(main, "_orienter_boot_vm_windows", orienter)
    return appels


def test_le_wake_on_lan_n_existe_plus(client, admin_headers, clean_db):
    _machine()
    assert client.post(f"/machines/{MAC}/wol", headers=admin_headers).status_code in (404, 405)
    assert not hasattr(main, "wakeonlan")


def test_redeployer_renvoie_la_vm_sur_son_cd(client, admin_headers, clean_db, monkeypatch):
    _machine()
    appels = _espion(monkeypatch)
    r = client.post(f"/machines/{MAC}/redeploy-now", headers=admin_headers)
    assert r.status_code == 200
    assert "WoL" not in r.json()["detail"]
    assert appels == [(MAC, True)]


def test_le_redeploiement_en_lot_aussi(client, admin_headers, clean_db, monkeypatch):
    """C'est lui qui oubliait la VM Windows."""
    _machine()
    appels = _espion(monkeypatch)
    r = client.post("/machines/batch-status", headers=admin_headers,
                    json={"macs": [MAC], "status": "pending"})
    assert r.json()["updated"] == [MAC]
    assert appels == [(MAC, True)]


def test_un_lot_qui_ne_redeploie_pas_ne_touche_pas_au_demarrage(client, admin_headers, clean_db, monkeypatch):
    _machine()
    appels = _espion(monkeypatch)
    client.post("/machines/batch-status", headers=admin_headers, json={"macs": [MAC], "status": "failed"})
    assert appels == []
