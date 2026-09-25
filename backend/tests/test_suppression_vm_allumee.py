# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Supprimer une VM allumée la laissait tourner, sans fiche.

L'arrêt Proxmox est asynchrone : il rend la main avec une tâche, la VM tourne
encore, et le DELETE enchaîné aussitôt était refusé (« VM is running - destroy
failed »). L'erreur était avalée, la fiche retirée, et l'interface annonçait
« supprimée » : la VM restait allumée, son adresse IP avec, et OSIRIS ne la
connaissait plus. Une VM déployée étant TOUJOURS allumée, c'était le cas de
chaque suppression depuis l'interface. Vu le 25/09 sur deux VM de test.
"""
import asyncio

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

import main
from models import Hypervisor, Machine, engine

from .conftest import UUID_VM_TEST, config_vm_conforme

MAC = "aabbccddeeff"
UPID_STOP = "UPID:pve:0001:stop"
UPID_DEL = "UPID:pve:0002:del"


def _proxmox_realiste(monkeypatch, *, destruction_ok=True) -> list:
    """Faux Proxmox qui refuse, comme le vrai, de détruire une VM pas encore arrêtée."""
    etat = {"allumee": True}
    appels: list = []

    async def fake_get(h, path):
        return config_vm_conforme() if path.endswith("/config") else {}

    async def fake_post(h, path, data=None):
        appels.append(path)
        return UPID_STOP if path.endswith("status/stop") else {}

    async def fake_wait(h, node, upid, max_wait=120):
        appels.append(f"attente {upid}")
        if upid == UPID_STOP:
            etat["allumee"] = False

    async def fake_request(h, method, path, data=None):
        appels.append(f"{method} {path}")
        if etat["allumee"]:
            raise HTTPException(status_code=502, detail="Proxmox 500: VM is running - destroy failed")
        if not destruction_ok:
            raise HTTPException(status_code=502, detail="Proxmox 500: storage locked")
        return UPID_DEL

    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    monkeypatch.setattr(main, "_proxmox_post", fake_post)
    monkeypatch.setattr(main, "_proxmox_wait_task", fake_wait)
    monkeypatch.setattr(main, "_proxmox_request", fake_request)
    return appels


def test_l_arret_est_attendu_avant_la_destruction(monkeypatch):
    appels = _proxmox_realiste(monkeypatch)
    h = Hypervisor(id=1, name="pve", url="https://pve.test:8006", type="proxmox")

    asyncio.run(main._destroy_vm_quietly(h, "pve", 150, strict=True))

    stop = appels.index(f"attente {UPID_STOP}")
    delete = next(i for i, a in enumerate(appels) if a.startswith("DELETE"))
    assert stop < delete, appels
    assert f"attente {UPID_DEL}" in appels, "la fin de la destruction est attendue aussi"


def test_un_echec_de_destruction_remonte_quand_la_suppression_est_demandee(monkeypatch):
    _proxmox_realiste(monkeypatch, destruction_ok=False)
    h = Hypervisor(id=1, name="pve", url="https://pve.test:8006", type="proxmox")

    with pytest.raises(HTTPException) as err:
        asyncio.run(main._destroy_vm_quietly(h, "pve", 150, strict=True))
    assert err.value.status_code == 502
    assert "fiche est conservée" in err.value.detail


def test_le_nettoyage_apres_echec_de_creation_reste_silencieux(monkeypatch):
    """Là, l'erreur qui compte est celle de la création : ne pas la masquer."""
    _proxmox_realiste(monkeypatch, destruction_ok=False)
    h = Hypervisor(id=1, name="pve", url="https://pve.test:8006", type="proxmox")
    asyncio.run(main._destroy_vm_quietly(h, "pve", 150))


def _vm_de_test() -> None:
    with Session(engine) as session:
        h = Hypervisor(name="pve-test", url="https://pve.test:8006", type="proxmox",
                       token_id="root@pam!osiris", token_secret="")
        session.add(h)
        session.commit()
        session.refresh(h)
        m = session.exec(select(Machine).where(Machine.mac == MAC)).first()
        m.hypervisor_id, m.proxmox_vm_id, m.proxmox_node, m.vm_uuid = h.id, 123, "pve", UUID_VM_TEST
        session.add(m)
        session.commit()


def test_la_fiche_reste_si_la_vm_n_a_pas_pu_etre_detruite(client, test_machine, admin_headers,
                                                            monkeypatch):
    _vm_de_test()
    _proxmox_realiste(monkeypatch, destruction_ok=False)

    resp = client.delete(f"/machines/{MAC}?destroy_proxmox=true", headers=admin_headers)

    assert resp.status_code == 502, resp.text
    with Session(engine) as session:
        assert session.exec(select(Machine).where(Machine.mac == MAC)).first() is not None


def test_une_vm_allumee_est_bien_supprimee_avec_sa_fiche(client, test_machine, admin_headers,
                                                         monkeypatch):
    _vm_de_test()
    appels = _proxmox_realiste(monkeypatch)

    resp = client.delete(f"/machines/{MAC}?destroy_proxmox=true", headers=admin_headers)

    assert resp.status_code == 204, resp.text
    assert any(a.startswith("DELETE") and "purge=1" in a for a in appels)
    with Session(engine) as session:
        assert session.exec(select(Machine).where(Machine.mac == MAC)).first() is None
