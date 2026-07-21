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
