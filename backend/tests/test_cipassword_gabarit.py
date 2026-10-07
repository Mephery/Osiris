# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Un clone Proxmox n'hérite jamais du mot de passe cloud-init de son gabarit.

Le lecteur cloud-init est recopié par le clone, `cipassword` compris. Le 9003
(Nova, FIT) portait celui de sa construction : cloud-init l'aurait posé sur le
compte du profil, le même sur toutes les VM du gabarit (vu le 07/10).
"""
import main
from tests.test_create_vm_template import _corps, _make_hypervisor, _patch


def _avec_cipassword(monkeypatch, present: bool):
    original = main._proxmox_get

    async def get(h, path):
        r = await original(h, path)
        if path.endswith("/config") and isinstance(r, dict):
            r = {**r, "ide2": "ceph:vm-150-cloudinit,media=cdrom,size=4M"}
            if present:
                r["cipassword"] = "**********"
        return r
    monkeypatch.setattr(main, "_proxmox_get", get)


def _deletes(cap) -> list[str]:
    return [d.get("delete", "") for _, d in cap.get("puts", []) if d.get("delete")]


def test_clone_cloudinit_retire_le_mot_de_passe_du_gabarit(client, admin_headers, monkeypatch):
    hv = _make_hypervisor()
    cap: dict = {}
    _patch(monkeypatch, cap)
    _avec_cipassword(monkeypatch, True)
    r = client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers,
                    json=_corps(os="ubuntu", hostname="srv-ci", template_id=9001,
                                boot_mode="cloudinit", disk_gb=20))
    assert r.status_code == 201, r.text
    assert any("cipassword" in d for d in _deletes(cap))


def test_clone_nu_retire_le_mot_de_passe_mais_garde_le_lecteur_cloudinit(client, admin_headers, monkeypatch):
    """Sans son lecteur, cloud-init se désactive, et le réseau de l'image — lié
    à la MAC de la VM de construction — ne s'applique plus : carte éteinte,
    aucune demande DHCP (FIT, 07/10)."""
    hv = _make_hypervisor()
    cap: dict = {}
    _patch(monkeypatch, cap)
    _avec_cipassword(monkeypatch, True)
    r = client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers,
                    json=_corps(os="ubuntu", hostname="srv-nu", template_id=9001, disk_gb=20))
    assert r.status_code == 201, r.text
    assert _deletes(cap) == ["cipassword"]


def test_clone_nu_retire_toujours_un_vrai_cd(client, admin_headers, monkeypatch):
    """Le CD WinPE qu'un gabarit Windows traîne de sa construction, lui, part."""
    hv = _make_hypervisor()
    cap: dict = {}
    _patch(monkeypatch, cap)
    original = main._proxmox_get

    async def get(h, path):
        r = await original(h, path)
        if path.endswith("/config") and isinstance(r, dict):
            r = {**r, "ide2": "local:iso/osiris-winpe.iso,media=cdrom"}
        return r
    monkeypatch.setattr(main, "_proxmox_get", get)
    r = client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers, json=_corps())
    assert r.status_code == 201, r.text
    assert _deletes(cap) == ["ide2"]


def test_sans_mot_de_passe_au_gabarit_rien_n_est_demande(client, admin_headers, monkeypatch):
    """Proxmox refuserait-il un `delete` d'une option absente ? On ne le lui
    demande pas : seulement ce qui existe."""
    hv = _make_hypervisor()
    cap: dict = {}
    _patch(monkeypatch, cap)
    _avec_cipassword(monkeypatch, False)
    client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers,
                json=_corps(os="ubuntu", hostname="srv-ci", template_id=9001,
                            boot_mode="cloudinit", disk_gb=20))
    assert not any("cipassword" in d for d in _deletes(cap))
