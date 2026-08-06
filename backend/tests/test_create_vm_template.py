# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Mode `template` : clone d'un template Proxmox sans injection.

C'est le pendant du clone Linux cloud-init, mais nu : rien n'est injecté (ni
user-data, ni snippet, ni lecteur cloud-init). Le clone porte déjà son agent
d'amorçage (cuit dans le template) ; il lit sa propre MAC au démarrage et rappelle
OSIRIS. C'est ce qui masterise les VM Windows depuis un template sysprepé.
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


def _patch(monkeypatch, captured: dict, *, disque_template_gb: int = 80):
    async def fake_get(h, path):
        if path.endswith("/cluster/nextid"):
            return "150"
        if path.endswith("/config"):
            # Config du clone, lue par _agrandir_disque_si_besoin.
            return {"sata0": f"Lab_CEPH:vm-150-disk-1,size={disque_template_gb}G",
                    "scsi0": f"Lab_CEPH:vm-150-disk-0,size={disque_template_gb}G"}
        return {}

    async def fake_post(h, path, data=None):
        if path.endswith("/clone"):
            captured["clone_path"] = path
            captured["clone"] = data
        if path.endswith("/status/start"):
            captured["started"] = True
        return "UPID:pve:task"

    async def fake_put(h, path, data):
        captured.setdefault("puts", []).append((path, data))
        if path.endswith("/config"):
            captured["config"] = data
        return {}

    async def fake_request(h, method, path, data=None):
        if path.endswith("/resize"):
            captured["resize"] = data
        return {}

    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    monkeypatch.setattr(main, "_proxmox_post", fake_post)
    monkeypatch.setattr(main, "_proxmox_put", fake_put)
    monkeypatch.setattr(main, "_proxmox_request", fake_request)
    monkeypatch.setattr(main, "_proxmox_wait_task", lambda *a, **k: _noop())


async def _noop():
    return None


def _corps(**o):
    base = dict(hostname="SRV-CLONE", client="Acme", os="windows",
                node="pve", storage="Lab_CEPH", bridge="vmbr0.238",
                boot_mode="template", template_id=100, disk_gb=80)
    base.update(o)
    return base


def test_template_windows_clone_avec_mac_neuve_et_boot_disque(client, admin_headers, monkeypatch):
    hv = _make_hypervisor()
    cap: dict = {}
    _patch(monkeypatch, cap)

    r = client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers, json=_corps())
    assert r.status_code == 201, r.text

    assert cap["clone_path"].endswith("/qemu/100/clone")     # clone du template 100
    assert cap["clone"]["full"] == 1
    cfg = cap["config"]
    assert cfg["net0"].startswith("e1000=")                  # matériel Windows
    # MAC neuve, PAS celle héritée du template (sinon collision réseau).
    assert "=" in cfg["net0"] and cfg["net0"].split("=")[1].split(",")[0]
    assert cfg["boot"] == "order=sata0"                      # boot disque, pas de CD
    assert "cicustom" not in cfg and "ide2" not in cfg       # aucune injection


def test_template_linux_sort_en_virtio(client, admin_headers, monkeypatch):
    hv = _make_hypervisor()
    cap: dict = {}
    _patch(monkeypatch, cap)

    r = client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers,
                    json=_corps(os="ubuntu", hostname="SRV-LX"))
    assert r.status_code == 201, r.text
    assert cap["config"]["net0"].startswith("virtio=")
    assert cap["config"]["boot"] == "order=scsi0"


def test_disque_agrandi_seulement_si_plus_grand(client, admin_headers, monkeypatch):
    hv = _make_hypervisor()
    cap: dict = {}
    _patch(monkeypatch, cap, disque_template_gb=80)

    # Demandé plus grand (120 > 80) → resize.
    client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers,
                json=_corps(disk_gb=120))
    assert cap.get("resize") == {"disk": "sata0", "size": "120G"}


def test_disque_egal_au_template_nest_pas_redimensionne(client, admin_headers, monkeypatch):
    hv = _make_hypervisor()
    cap: dict = {}
    _patch(monkeypatch, cap, disque_template_gb=80)

    # Demandé égal (80 = 80) → PAS de resize (Proxmox refuserait « même taille »).
    client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers,
                json=_corps(disk_gb=80))
    assert "resize" not in cap


def test_windows_refuse_le_mode_cloudinit(client, admin_headers, monkeypatch):
    hv = _make_hypervisor()
    _patch(monkeypatch, {})
    r = client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers,
                    json=_corps(boot_mode="cloudinit"))
    assert r.status_code == 400
    assert "cloud-init" in r.text.lower()


def test_template_sans_id_est_refuse(client, admin_headers, monkeypatch):
    hv = _make_hypervisor()
    _patch(monkeypatch, {})
    r = client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers,
                    json=_corps(template_id=None))
    assert r.status_code == 400
    assert "template_id" in r.text
