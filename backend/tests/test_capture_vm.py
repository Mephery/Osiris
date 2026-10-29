# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Capture d'une VM Windows : OSIRIS la met sur WinPE, puis la rend à son disque.

Une VM d'OSIRIS ne démarre pas en PXE, WinPE lui arrive par CD. Enregistrer la
capture ne touchait pas à la VM : elle redémarrait sur son disque, la machine de
référence sysprepée faisait son OOBE, et la capture n'avait jamais lieu. Et après
une capture, le redémarrage final ramenait la VM sur WinPE, qui recapturait le
même disque en boucle.
"""
import pytest
from sqlmodel import Session

import main
from models import Hypervisor, Machine, engine

MAC = "aabbccddee40"


@pytest.fixture
def hv(clean_db, tmp_path, monkeypatch):
    """Une VM Windows sur un faux Proxmox, qui journalise chaque écriture."""
    depot, partage = tmp_path / "captures", tmp_path / "windows"
    depot.mkdir()
    partage.mkdir()
    monkeypatch.setattr(main, "CAPTURE_SHARE_PATH", str(depot))
    monkeypatch.setattr(main, "WIN_SHARE_PATH", str(partage))
    main._capture_jobs.clear()
    with Session(engine) as s:
        h = Hypervisor(name="pve", url="https://pve.test:8006", type="proxmox")
        s.add(h)
        s.commit()
        s.add(Machine(mac=MAC, hostname="REF-W11", client="c", os="windows", status="deployed",
                      hypervisor_id=h.id, proxmox_vm_id=150, proxmox_node="n1"))
        s.commit()
        hv_obj = h
    etat = {"status": "stopped", "ide2": "local:iso/osiris-winpe.iso,media=cdrom", "ecrit": []}

    async def verifiee(mac, action, **_):
        return hv_obj, 150, "n1"

    async def get(h, chemin):
        if chemin.endswith("/config"):
            return {"ide2": etat["ide2"]} if etat["ide2"] else {}
        if chemin.endswith("/status/current"):
            return {"status": etat["status"]}
        return {}

    async def put(h, chemin, data):
        etat["ecrit"].append(("PUT", chemin.rsplit("/", 1)[-1], data))
        return {}

    async def post(h, chemin, data=None):
        etat["ecrit"].append(("POST", chemin.rsplit("/", 1)[-1], data))
        return {}

    monkeypatch.setattr(main, "_vm_verifiee", verifiee)
    monkeypatch.setattr(main, "_proxmox_get", get)
    monkeypatch.setattr(main, "_proxmox_put", put)
    monkeypatch.setattr(main, "_proxmox_post", post)
    yield etat, depot
    main._capture_jobs.clear()


def _enregistrer(client, admin_headers):
    return client.post("/capture/register", params={"mac": MAC, "wim_name": "Golden_W11"},
                       headers=admin_headers)


def test_une_vm_eteinte_est_demarree_sur_winpe(client, admin_headers, hv):
    etat, _ = hv
    r = _enregistrer(client, admin_headers)
    assert r.status_code == 200
    assert etat["ecrit"] == [("PUT", "config", {"boot": "order=ide2;sata0"}), ("POST", "start", None)]
    assert "démarrée sur WinPE" in r.json()["consigne"]


def test_une_vm_allumee_n_est_jamais_coupee(client, admin_headers, hv):
    """Elle tourne Windows, peut-être pas encore sysprepé : la couper ferait une image inutilisable."""
    etat, _ = hv
    etat["status"] = "running"
    r = _enregistrer(client, admin_headers)
    assert r.status_code == 200
    assert etat["ecrit"] == [("PUT", "config", {"boot": "order=ide2;sata0"})]
    assert "sysprep" in r.json()["consigne"]


def test_sans_lecteur_cd_le_refus_est_dit_et_rien_n_est_enregistre(client, admin_headers, hv):
    etat, _ = hv
    etat["ide2"] = ""
    r = _enregistrer(client, admin_headers)
    assert r.status_code == 409 and "ide2" in r.json()["detail"]
    assert etat["ecrit"] == []
    assert MAC not in main._capture_jobs


def test_une_machine_physique_n_a_pas_de_consigne(client, admin_headers, hv):
    with Session(engine) as s:
        s.add(Machine(mac="aabbccddee41", hostname="PC-41", client="c", os="windows"))
        s.commit()
    r = client.post("/capture/register", params={"mac": "aabbccddee41", "wim_name": "G"},
                    headers=admin_headers)
    assert r.status_code == 200 and r.json()["consigne"] is None
    assert hv[0]["ecrit"] == []


def test_capture_reussie_la_vm_est_eteinte_sur_son_disque(client, admin_headers, hv):
    etat, depot = hv
    _enregistrer(client, admin_headers)
    main._build_capture_script(MAC)
    (depot / "Golden_W11.wim").write_bytes(b"wim")
    etat["ecrit"].clear()
    client.post(f"/capture/{MAC}/done", params={"success": "true"})
    assert etat["ecrit"] == [("PUT", "config", {"boot": "order=sata0"}), ("POST", "stop", None)]


def test_capture_ratee_la_vm_reste_sur_winpe(client, admin_headers, hv):
    """Son écran dit quoi faire, et une capture manuelle reste possible."""
    etat, _ = hv
    _enregistrer(client, admin_headers)
    main._build_capture_script(MAC)
    etat["ecrit"].clear()
    client.post(f"/capture/{MAC}/done", params={"success": "false"})
    assert etat["ecrit"] == []


def test_une_capture_terminee_n_est_pas_refaite(client, admin_headers, hv):
    _, depot = hv
    with Session(engine) as s:
        m = s.exec(main.select(Machine).where(Machine.mac == MAC)).first()
        m.hw_serial = "SERIE-REF"
        s.add(m)
        s.commit()
    _enregistrer(client, admin_headers)
    assert "dism /Capture-Image" in client.get("/winpe-auto", params={"serial": "SERIE-REF"}).text
    (depot / "Golden_W11.wim").write_bytes(b"wim")
    client.post(f"/capture/{MAC}/done", params={"success": "true"})
    script = client.get("/winpe-auto", params={"serial": "SERIE-REF"}).text
    assert "deja terminee" in script
    assert "dism" not in script.lower()
