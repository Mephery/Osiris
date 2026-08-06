# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Bascule de l'ordre de démarrage des VM Windows.

Une VM ne sait pas amorcer par le réseau — l'OVMF de Proxmox n'expose aucune entrée
PXE — donc WinPE lui arrive par CD-ROM. Il faut alors dire à la VM quand regarder ce
CD, et seul OSIRIS le sait :

- à la création et au redéploiement, le CD d'abord ;
- dès que WinPE annonce la fin (juste avant SON reboot), le disque seul.

Les deux sens comptent. Sans le second, la VM rebooterait indéfiniment sur WinPE au
lieu de lancer son Windows ; sans le premier, un redéploiement resterait lettre morte,
le disque installé gardant la main.
"""
import asyncio

import main
from models import Hypervisor, Machine, engine
from sqlmodel import Session, select

MAC = "aabbccddeeff"


def _fait_de_la_machine_une_vm(os_machine: str = "windows", type_hv: str = "proxmox") -> None:
    with Session(engine) as session:
        h = Hypervisor(name="pve-test", url="https://pve.test:8006", type=type_hv,
                       token_id="root@pam!osiris", token_secret="")
        session.add(h)
        session.commit()
        session.refresh(h)
        m = session.exec(select(Machine).where(Machine.mac == MAC)).first()
        m.hypervisor_id, m.proxmox_vm_id, m.proxmox_node = h.id, 123, "pve"
        m.os = os_machine
        session.add(m)
        session.commit()


def _capture_put(monkeypatch, boot_en_attente: bool = False) -> dict:
    """
    Branche les trois appels Proxmox utilisés par la bascule.

    `boot_en_attente` simule ce que répond une VM ALLUMÉE : Proxmox met la
    modification de côté au lieu de l'appliquer.
    """
    vu: dict = {"actions": []}

    async def fake_put(h, path, data):
        vu["path"], vu["data"] = path, data
        return {}

    async def fake_get(h, path):
        if path.endswith("/pending"):
            return [{"key": "boot", "value": "order=ide2;sata0",
                     **({"pending": "order=sata0"} if boot_en_attente else {})}]
        return {}

    async def fake_post(h, path, data=None):
        vu["actions"].append(path.rsplit("/", 1)[-1])
        return {}

    monkeypatch.setattr(main, "_proxmox_put", fake_put)
    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    monkeypatch.setattr(main, "_proxmox_post", fake_post)
    # Le vrai `sleep` est capturé AVANT d'être remplacé : `main.asyncio` est le
    # module asyncio lui-même, donc un lambda qui appellerait `asyncio.sleep`
    # s'appellerait lui-même — récursion que le `except` large de la bascule
    # avalerait en silence, en faisant juste disparaître le redémarrage.
    vrai_sleep = asyncio.sleep
    monkeypatch.setattr(main.asyncio, "sleep", lambda _: vrai_sleep(0))
    return vu


def test_fin_de_deploiement_renvoie_la_vm_sur_son_disque(client, test_machine, monkeypatch):
    """Sans ça, la VM rebooterait sur WinPE au lieu de démarrer le Windows fraîchement posé."""
    _fait_de_la_machine_une_vm()
    vu = _capture_put(monkeypatch)

    assert client.post(f"/machines/{MAC}/status", params={"status": "deployed"}).status_code == 200

    assert vu["data"] == {"boot": "order=sata0"}
    assert vu["path"].endswith("/qemu/123/config")


def test_redeploiement_ramene_la_vm_sur_le_cd_winpe(client, test_machine, monkeypatch):
    """Une VM n'a pas de WoL : la renvoyer sur son CD est le seul moyen de la redéployer."""
    _fait_de_la_machine_une_vm()
    vu = _capture_put(monkeypatch)

    assert client.post(f"/machines/{MAC}/status", params={"status": "pending"}).status_code == 200

    assert vu["data"] == {"boot": "order=ide2;sata0"}


def test_le_bouton_redeployer_ramene_aussi_sur_le_cd(client, test_machine, admin_headers,
                                                     monkeypatch):
    _fait_de_la_machine_une_vm()
    vu = _capture_put(monkeypatch)

    resp = client.post(f"/machines/{MAC}/redeploy-now", headers=admin_headers)
    assert resp.status_code == 200, resp.text

    assert vu["data"] == {"boot": "order=ide2;sata0"}


def test_une_vm_linux_nest_pas_touchee(client, test_machine, monkeypatch):
    """Le chemin Linux est le clone d'un template : il n'a ni CD ni WinPE."""
    _fait_de_la_machine_une_vm(os_machine="ubuntu")
    vu = _capture_put(monkeypatch)

    client.post(f"/machines/{MAC}/status", params={"status": "deployed"})

    assert "data" not in vu, "aucun ordre de démarrage ne devait être écrit"
    assert vu["actions"] == []


def test_une_machine_physique_nest_pas_touchee(client, test_machine, monkeypatch):
    """Un poste physique amorce en PXE : son ordre de démarrage ne regarde pas OSIRIS."""
    vu = _capture_put(monkeypatch)   # machine laissée sans hyperviseur ni vmid

    client.post(f"/machines/{MAC}/status", params={"status": "deployed"})

    assert "data" not in vu, "aucun ordre de démarrage ne devait être écrit"
    assert vu["actions"] == []


def test_une_vm_vsphere_nest_pas_touchee(client, test_machine, monkeypatch):
    """vSphere gère ses lecteurs autrement — l'ordre Proxmox n'y a aucun sens."""
    _fait_de_la_machine_une_vm(type_hv="vsphere")
    vu = _capture_put(monkeypatch)

    client.post(f"/machines/{MAC}/status", params={"status": "deployed"})

    assert "data" not in vu, "aucun ordre de démarrage ne devait être écrit"
    assert vu["actions"] == []


def test_un_ordre_reste_en_attente_declenche_un_cycle_dalimentation(client, test_machine,
                                                                    monkeypatch):
    """
    La régression du 2026-08-06. Proxmox met de côté toute modification faite sur une
    VM allumée : le redémarrage que WinPE déclenche lui-même ne relit pas la
    configuration, la VM repart sur le CD et seul le garde-fou anti-redéploiement
    évite l'effacement du Windows tout juste installé.
    """
    _fait_de_la_machine_une_vm()
    vu = _capture_put(monkeypatch, boot_en_attente=True)

    client.post(f"/machines/{MAC}/status", params={"status": "deployed"})

    assert vu["data"] == {"boot": "order=sata0"}
    assert vu["actions"] == ["stop", "start"], "seul un nouveau processus QEMU relit la config"


def test_sans_rien_en_attente_la_vm_nest_pas_redemarree(client, test_machine, monkeypatch):
    """
    « deployed » est posté DEUX fois : par WinPE avant son reboot, puis par le
    firstboot après l'OOBE. Au second, tout est déjà appliqué — couper la machine
    de force interromprait un Windows en pleine configuration.
    """
    _fait_de_la_machine_une_vm()
    vu = _capture_put(monkeypatch, boot_en_attente=False)

    client.post(f"/machines/{MAC}/status", params={"status": "deployed"})

    assert vu["data"] == {"boot": "order=sata0"}
    assert vu["actions"] == [], "aucun cycle d'alimentation ne devait avoir lieu"


def test_un_hyperviseur_injoignable_ne_fait_pas_echouer_le_rapport(client, test_machine,
                                                                   monkeypatch):
    """
    Le rapport de statut est la seule voix de la machine : un hyperviseur muet ne doit
    jamais l'étouffer.
    """
    _fait_de_la_machine_une_vm()

    async def put_qui_echoue(h, path, data):
        raise RuntimeError("hyperviseur injoignable")

    monkeypatch.setattr(main, "_proxmox_put", put_qui_echoue)

    resp = client.post(f"/machines/{MAC}/status", params={"status": "deployed"})
    assert resp.status_code == 200

    with Session(engine) as session:
        m = session.exec(select(Machine).where(Machine.mac == MAC)).first()
    assert m.status == "deployed"
