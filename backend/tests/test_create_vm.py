# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Tests de l'assemblage matériel des VM Proxmox (create_vm).

On mocke les appels Proxmox pour capturer le payload `qemu` envoyé et vérifier
que les VM Windows sortent en OVMF/SATA/e1000 (pilotes inbox, aucun virtio) et
que les VM Linux gardent le matériel virtio historique.
"""
from sqlmodel import Session

import main
from models import engine, Hypervisor


def _make_hypervisor() -> int:
    with Session(engine) as session:
        h = Hypervisor(name="pve-test", url="https://pve.test:8006",
                       token_id="root@pam!osiris", token_secret="", tls_verify=False)
        session.add(h)
        session.commit()
        session.refresh(h)
        return h.id


def _patch_proxmox(monkeypatch, captured: dict):
    async def fake_get(h, path):
        if path.endswith("/cluster/nextid"):
            return "150"
        return {}

    async def fake_post(h, path, data=None):
        if path.endswith("/qemu"):
            captured["qemu"] = data
        return "UPID:pve:task"

    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    monkeypatch.setattr(main, "_proxmox_post", fake_post)


def test_create_vm_windows_hardware(client, admin_headers, monkeypatch):
    hv_id = _make_hypervisor()
    captured: dict = {}
    _patch_proxmox(monkeypatch, captured)

    resp = client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": "SRV-WIN", "client": "Acme", "os": "windows",
        "node": "pve", "storage": "local-lvm", "bridge": "vmbr0",
        "vcpus": 4, "ram_mb": 4096, "disk_gb": 60, "boot_mode": "pxe",
    })
    assert resp.status_code == 201, resp.text

    cfg = captured["qemu"]
    assert cfg["ostype"] == "win11"
    assert cfg["bios"] == "ovmf"
    assert cfg["machine"] == "q35"
    assert "efidisk0" in cfg
    assert cfg["net0"].startswith("e1000=")
    assert cfg["sata0"].startswith("local-lvm:60")
    # Pas de matériel virtio (Windows = pilotes inbox uniquement)
    assert "scsi0" not in cfg and "scsihw" not in cfg
    assert "virtio" not in cfg["net0"]


def test_create_vm_windows_ostype_override(client, admin_headers, monkeypatch):
    """win_ostype permet de cibler Server 2016/2019 (win10)."""
    hv_id = _make_hypervisor()
    captured: dict = {}
    _patch_proxmox(monkeypatch, captured)

    resp = client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": "SRV-2019", "client": "Acme", "os": "windows", "win_ostype": "win10",
        "node": "pve", "storage": "local-lvm", "boot_mode": "pxe",
    })
    assert resp.status_code == 201, resp.text
    assert captured["qemu"]["ostype"] == "win10"


def test_create_vm_linux_stays_virtio(client, admin_headers, monkeypatch):
    hv_id = _make_hypervisor()
    captured: dict = {}
    _patch_proxmox(monkeypatch, captured)

    resp = client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": "srv-linux", "client": "Acme", "os": "ubuntu",
        "node": "pve", "storage": "local-lvm", "boot_mode": "pxe",
    })
    assert resp.status_code == 201, resp.text

    cfg = captured["qemu"]
    assert cfg["ostype"] == "l26"
    assert cfg["net0"].startswith("virtio=")
    assert cfg["scsihw"] == "virtio-scsi-pci"
    assert "bios" not in cfg and "efidisk0" not in cfg


def test_la_fiche_est_ecrite_avant_le_moindre_appel_proxmox(client, admin_headers, monkeypatch):
    """
    Une VM créée avant sa fiche devient invisible si la requête est interrompue
    entre les deux : ni inventaire, ni audit. La fiche doit donc exister d'abord,
    quitte à laisser une fiche sans VM — visible, elle, et supprimable.
    """
    from sqlmodel import select
    from models import Machine

    hv_id = _make_hypervisor()
    ordre: list = []

    async def fake_get(h, path):
        return "150" if path.endswith("/cluster/nextid") else {}

    async def fake_post(h, path, data=None):
        with Session(engine) as session:
            fiche = session.exec(select(Machine).where(Machine.hostname == "srv-linux")).first()
        ordre.append(("proxmox", fiche is not None))
        return "UPID:pve:task"

    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    monkeypatch.setattr(main, "_proxmox_post", fake_post)

    resp = client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": "srv-linux", "client": "Acme", "os": "ubuntu",
        "node": "pve", "storage": "local-lvm", "boot_mode": "pxe",
    })
    assert resp.status_code == 201, resp.text
    assert ordre and all(fiche_presente for _, fiche_presente in ordre), \
        "la fiche doit déjà exister au premier appel Proxmox"


def test_echec_hyperviseur_detruit_la_vm_retire_la_fiche_et_laisse_une_trace(
        client, admin_headers, monkeypatch):
    from sqlmodel import select
    from models import Machine, AuditLog

    hv_id = _make_hypervisor()

    async def fake_get(h, path):
        return "150" if path.endswith("/cluster/nextid") else {}

    async def fake_post(h, path, data=None):
        if path.endswith("/status/start"):
            raise RuntimeError("hyperviseur injoignable")
        return "UPID:pve:task"

    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    monkeypatch.setattr(main, "_proxmox_post", fake_post)

    destroyed: list = []

    async def fake_destroy(h, node, vm_id):
        destroyed.append(vm_id)

    monkeypatch.setattr(main, "_destroy_vm_quietly", fake_destroy)

    # L'erreur d'origine remonte telle quelle (le client de test ne l'avale pas) :
    # ce qui compte ici est le nettoyage effectué au passage.
    import pytest
    with pytest.raises(RuntimeError, match="hyperviseur injoignable"):
        client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
            "hostname": "srv-rate", "client": "Acme", "os": "ubuntu",
            "node": "pve", "storage": "local-lvm", "boot_mode": "pxe",
        })

    assert destroyed == [150], "la VM doit être détruite, pas laissée orpheline"
    with Session(engine) as session:
        assert session.exec(select(Machine).where(Machine.hostname == "srv-rate")).first() is None, \
            "la fiche d'une VM qui n'existe pas doit être retirée"
        trace = session.exec(select(AuditLog).where(AuditLog.action == "create_vm_failed")).first()
        assert trace is not None, "l'audit doit garder trace de la tentative"
        assert '"vm_id": 150' in trace.details
        assert "hyperviseur injoignable" in trace.details


def test_mac_deja_prise_nempeche_toute_creation_de_vm(client, admin_headers, monkeypatch):
    """Si la fiche ne peut pas être écrite, aucune VM ne doit être créée."""
    from models import Machine

    hv_id = _make_hypervisor()
    captured: dict = {}
    _patch_proxmox(monkeypatch, captured)

    monkeypatch.setattr(main.secrets, "token_bytes", lambda n: b"\xaa" * n)
    with Session(engine) as session:
        session.add(Machine(mac="02" + "aa" * 5, hostname="DEJA-LA", client="X", os="ubuntu"))
        session.commit()

    resp = client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": "srv-linux", "client": "Acme", "os": "ubuntu",
        "node": "pve", "storage": "local-lvm", "boot_mode": "pxe",
    })
    assert resp.status_code == 500
    assert "qemu" not in captured, "aucune VM ne doit avoir été créée"


def test_create_vm_windows_rejects_cloudinit(client, admin_headers, monkeypatch):
    hv_id = _make_hypervisor()
    captured: dict = {}
    _patch_proxmox(monkeypatch, captured)

    resp = client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": "SRV-WIN", "client": "Acme", "os": "windows",
        "node": "pve", "storage": "local-lvm", "boot_mode": "cloudinit",
        "cloud_template_id": 900,
    })
    assert resp.status_code == 400


# ── Lecteur cloud-init deja present sur le template ────────────────────────
# Le 2026-08-05, la creation d'une VM depuis un template regenere echouait sur
# « rbd create 'vm-106-cloudinit' error: (17) File exists », et le clone etait
# detruit dans la foulee. Cause : OSIRIS reclamait un lecteur cloud-init sans
# regarder si le clone en avait deja herite un.

import main


def test_un_template_avec_lecteur_cloudinit_est_reconnu():
    """Cas reel du 05/08 : `size=4M` = image materialisee, donc recopiee au clone."""
    assert main._a_un_lecteur_cloudinit({
        "ide2": "Lab_CEPH:vm-9001-cloudinit,media=cdrom,size=4M",
        "scsi0": "Lab_CEPH:base-9001-disk-0,size=3584M",
    })


def test_un_lecteur_sur_un_autre_emplacement_compte_aussi():
    """L'emplacement depend de la main qui a fabrique le template."""
    assert main._a_un_lecteur_cloudinit({"sata0": "local-lvm:vm-100-cloudinit"})
    assert main._a_un_lecteur_cloudinit({"scsi3": "ceph:vm-100-cloudinit,media=cdrom"})


def test_un_template_sans_lecteur_cloudinit():
    """Le cas nominal : OSIRIS doit alors en ajouter un."""
    assert not main._a_un_lecteur_cloudinit({
        "scsi0": "Lab_CEPH:base-9000-disk-0,size=3584M",
        "net0": "virtio=BC:24:11:A3:D6:5B,bridge=vmbr0.238",
        "boot": "order=scsi0",
    })


def test_une_config_vide_n_a_pas_de_lecteur():
    assert not main._a_un_lecteur_cloudinit({})


def test_les_valeurs_non_textuelles_ne_cassent_pas_le_balayage():
    """La config Proxmox mele chaines et entiers (cores, memory, onboot)."""
    assert not main._a_un_lecteur_cloudinit({"cores": 2, "memory": 2048, "onboot": 1})
