# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Garde-fou d'identité des VM : ne jamais agir sur une VM qui n'est pas la nôtre.

`proxmox_vm_id` est un ENTIER RECYCLÉ, pas une identité. `cluster/nextid` rend le
plus petit identifiant libre : une VM supprimée à la main sans retirer sa fiche
laisse donc un numéro qui repart au tourniquet, et la fiche se met à désigner la VM
d'un tiers. Chaque action d'OSIRIS frappait alors la mauvaise machine — purge,
rollback de snapshot, arrêt franc, et surtout retour sur le CD WinPE, qui
RÉINSTALLE le disque.

Ces tests fixent la règle inverse : en cas de doute sur l'identité, OSIRIS refuse
et ne touche à rien. Ils couvrent les trois chemins par lesquels une VM étrangère
pouvait être atteinte :

1. une fiche périmée qui désigne un numéro réattribué (la majorité des tests) ;
2. le rollback de création, qui détruisait un NUMÉRO sans vérifier à qui il est ;
3. la course sur `nextid`, qui n'a jamais réservé quoi que ce soit.
"""
import asyncio

import pytest
from sqlmodel import Session, select

import main
from models import AuditLog, Hypervisor, Machine, engine

from .conftest import UUID_VM_TEST, config_vm_conforme, config_vm_etrangere

MAC = "aabbccddeeff"


# ── Outillage ─────────────────────────────────────────────────────────────────

def _hyperviseur(pool: str = "") -> int:
    with Session(engine) as session:
        h = Hypervisor(name="pve-test", url="https://pve.test:8006", type="proxmox",
                       token_id="root@pam!osiris", token_secret="", pool=pool)
        session.add(h)
        session.commit()
        session.refresh(h)
        return h.id


def _vm(hv_id: int, *, vm_id: int = 123, uuid_vm: str = UUID_VM_TEST) -> None:
    """Fait de la machine de test une VM de cet hyperviseur."""
    with Session(engine) as session:
        m = session.exec(select(Machine).where(Machine.mac == MAC)).first()
        m.hypervisor_id, m.proxmox_vm_id, m.proxmox_node = hv_id, vm_id, "pve"
        m.vm_uuid = uuid_vm
        session.add(m)
        session.commit()


def _proxmox(monkeypatch, config: dict) -> dict:
    """Faux Proxmox qui répond `config` à toute lecture de configuration.

    `config = {}` simule ce que renvoyait un faux naïf ; en production, une VM
    absente fait échouer l'appel — cf. `_config_vm`, qui traduit ça en None.
    """
    vu: dict = {"ecritures": [], "actions": []}

    async def fake_get(h, path):
        if path.endswith("/config"):
            return config
        if path.endswith("/pending"):
            return [{"key": "boot", "value": "order=sata0"}]
        if path.endswith("/snapshot"):
            return []
        return {}

    async def fake_put(h, path, data):
        vu["ecritures"].append((path, data))
        return {}

    async def fake_post(h, path, data=None):
        vu["actions"].append(path)
        return {}

    async def fake_delete(h, path):
        vu["actions"].append("DELETE " + path)
        return {}

    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    monkeypatch.setattr(main, "_proxmox_put", fake_put)
    monkeypatch.setattr(main, "_proxmox_post", fake_post)
    monkeypatch.setattr(main, "_proxmox_delete", fake_delete)
    return vu


# ── 1. Une fiche périmée ne peut plus atteindre la VM d'un tiers ──────────────

def test_destruction_refusee_quand_le_numero_designe_une_autre_vm(
        client, test_machine, admin_headers, monkeypatch):
    """
    LE scénario redouté : la VM d'OSIRIS a été supprimée à la main, Proxmox a
    réattribué son numéro à une VM de production, et l'opérateur clique sur
    « supprimer + détruire la VM ». Sans garde-fou, la VM de production est purgée.
    """
    _vm(_hyperviseur())
    vu = _proxmox(monkeypatch, config_vm_etrangere())
    detruites: list = []

    async def fake_destroy(h, node, vm_id, nom_attendu=""):
        detruites.append(vm_id)

    monkeypatch.setattr(main, "_destroy_vm_quietly", fake_destroy)

    resp = client.delete(f"/machines/{MAC}?destroy_proxmox=true", headers=admin_headers)

    assert resp.status_code == 409, resp.text
    assert detruites == [], "aucune destruction ne devait être tentée"
    with Session(engine) as session:
        assert session.exec(select(Machine).where(Machine.mac == MAC)).first() is not None, \
            "la fiche est conservée : seul l'opérateur peut trancher ce qu'est devenue la VM"


def test_rollback_de_snapshot_refuse_sur_une_vm_etrangere(
        client, test_machine, admin_headers, monkeypatch):
    """Un retour arrière sur la mauvaise VM efface tout ce qu'elle a écrit depuis."""
    _vm(_hyperviseur())
    vu = _proxmox(monkeypatch, config_vm_etrangere())

    resp = client.post(f"/machines/{MAC}/snapshots/avant-maj/rollback", headers=admin_headers)

    assert resp.status_code == 409, resp.text
    assert vu["actions"] == [], "aucun rollback ne devait partir"


def test_arret_refuse_sur_une_vm_etrangere(client, test_machine, admin_headers, monkeypatch):
    """`stop` est un arrêt franc : sur la mauvaise VM, c'est une coupure de service."""
    _vm(_hyperviseur())
    vu = _proxmox(monkeypatch, config_vm_etrangere())

    resp = client.post(f"/machines/{MAC}/vm-power", headers=admin_headers,
                       json={"action": "stop"})

    assert resp.status_code == 409, resp.text
    assert vu["actions"] == []


def test_retour_sur_le_cd_winpe_refuse_sur_une_vm_etrangere(
        client, test_machine, admin_headers, monkeypatch):
    """
    Le chemin le plus destructeur d'OSIRIS : renvoyer une VM sur le CD WinPE, c'est
    réinstaller son disque. Le rapport de statut doit rester accepté (c'est la seule
    voix de la machine), mais l'hyperviseur ne doit pas être touché.
    """
    _vm(_hyperviseur())
    vu = _proxmox(monkeypatch, config_vm_etrangere())

    resp = client.post(f"/machines/{MAC}/status", params={"status": "pending"},
                       headers=admin_headers)

    assert resp.status_code == 200, resp.text
    assert vu["ecritures"] == [], "l'ordre de démarrage ne devait pas être réécrit"
    assert vu["actions"] == [], "aucun cycle d'alimentation ne devait avoir lieu"


def test_le_refus_laisse_une_trace_d_audit(client, test_machine, admin_headers, monkeypatch):
    """Un refus silencieux serait un incident invisible : il doit être traçable."""
    _vm(_hyperviseur())
    _proxmox(monkeypatch, config_vm_etrangere())

    client.post(f"/machines/{MAC}/vm-power", headers=admin_headers, json={"action": "stop"})

    with Session(engine) as session:
        trace = session.exec(
            select(AuditLog).where(AuditLog.action == "vm_identite_refusee")).first()
    assert trace is not None, "le refus doit être inscrit à l'audit"
    assert trace.target_mac == MAC
    assert "123" in trace.details


def test_une_vm_conforme_reste_pilotable(client, test_machine, admin_headers, monkeypatch):
    """Le garde-fou ne doit rien empêcher quand l'identité correspond."""
    _vm(_hyperviseur())
    vu = _proxmox(monkeypatch, config_vm_conforme())

    resp = client.post(f"/machines/{MAC}/vm-power", headers=admin_headers,
                       json={"action": "reboot"})

    assert resp.status_code == 200, resp.text
    assert any(a.endswith("/status/reboot") for a in vu["actions"])


def test_une_fiche_sans_ancre_est_identifiee_par_son_nom_puis_ancree(
        client, test_machine, admin_headers, monkeypatch):
    """
    Les fiches créées AVANT ce garde-fou n'ont pas d'UUID. Elles doivent continuer
    de fonctionner — sur le nom, seul repère disponible — et se faire ancrer au
    premier contrôle réussi, pour que le suivant porte sur l'ancre forte.
    """
    _vm(_hyperviseur(), uuid_vm="")          # fiche héritée : aucune ancre
    _proxmox(monkeypatch, config_vm_conforme(nom="PC-TEST"))

    resp = client.post(f"/machines/{MAC}/vm-power", headers=admin_headers,
                       json={"action": "start"})

    assert resp.status_code == 200, resp.text
    with Session(engine) as session:
        m = session.exec(select(Machine).where(Machine.mac == MAC)).first()
    assert m.vm_uuid == UUID_VM_TEST, "l'UUID relu doit être gravé dans la fiche"


def test_une_fiche_sans_ancre_au_nom_qui_ne_correspond_pas_est_refusee(
        client, test_machine, admin_headers, monkeypatch):
    _vm(_hyperviseur(), uuid_vm="")
    _proxmox(monkeypatch, config_vm_conforme(nom="AUTRE-CHOSE"))

    resp = client.post(f"/machines/{MAC}/vm-power", headers=admin_headers,
                       json={"action": "stop"})

    assert resp.status_code == 409, resp.text


def test_une_vm_disparue_est_annoncee_comme_telle(client, test_machine, admin_headers,
                                                  monkeypatch):
    """Une VM absente n'est pas une VM étrangère : le message doit distinguer les deux."""
    _vm(_hyperviseur())

    async def fake_get(h, path):
        raise main.HTTPException(status_code=502, detail="Proxmox 500: no such VM")

    monkeypatch.setattr(main, "_proxmox_get", fake_get)

    resp = client.post(f"/machines/{MAC}/vm-power", headers=admin_headers,
                       json={"action": "start"})

    assert resp.status_code == 404, resp.text
    assert "supprimée" in resp.json()["detail"]


# ── 2. Le rollback de création ne purge que SA VM ─────────────────────────────

def test_le_nettoyage_refuse_de_purger_une_vm_qui_nest_pas_la_sienne(monkeypatch):
    """
    La régression la plus grave de l'audit du 2026-08-10. Le rollback de création
    détruisait un NUMÉRO : `DELETE /qemu/<id>?purge=1`, précédé d'un arrêt franc
    (Proxmox refuse de détruire une VM allumée, donc « elle tourne » ne protégeait
    de rien). Or l'échec le plus banal du `POST /qemu` est « VM déjà existante » —
    auquel cas ce numéro appartient à un tiers, dont la VM était alors purgée.
    """
    h = Hypervisor(id=1, name="pve", url="https://pve.test:8006", type="proxmox")
    appels: list = []

    async def fake_get(h_, path):
        return config_vm_etrangere()          # ce numéro porte la VM d'un tiers

    async def fake_post(h_, path, data=None):
        appels.append(path)
        return {}

    async def fake_request(h_, method, path, data=None):
        appels.append(f"{method} {path}")
        return {}

    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    monkeypatch.setattr(main, "_proxmox_post", fake_post)
    monkeypatch.setattr(main, "_proxmox_request", fake_request)

    asyncio.run(main._destroy_vm_quietly(h, "pve", 150, nom_attendu="SRV-QUE-JE-CREE"))

    assert appels == [], "ni arrêt ni destruction ne devaient partir"


def test_le_nettoyage_detruit_bien_la_vm_du_deploiement(monkeypatch):
    """Le garde-fou ne doit pas empêcher le nettoyage légitime : sans lui, une VM à
    moitié configurée resterait sur l'hyperviseur, volumes compris."""
    h = Hypervisor(id=1, name="pve", url="https://pve.test:8006", type="proxmox")
    appels: list = []

    async def fake_get(h_, path):
        return {"name": "srv-que-je-cree", "smbios1": f"uuid={UUID_VM_TEST}"}

    async def fake_post(h_, path, data=None):
        appels.append(path)
        return {}

    async def fake_request(h_, method, path, data=None):
        appels.append(f"{method} {path}")
        return {}

    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    monkeypatch.setattr(main, "_proxmox_post", fake_post)
    monkeypatch.setattr(main, "_proxmox_request", fake_request)

    asyncio.run(main._destroy_vm_quietly(h, "pve", 150, nom_attendu="SRV-QUE-JE-CREE"))

    assert any("status/stop" in a for a in appels)
    assert any("purge=1" in a for a in appels), "la VM doit bien être purgée"


# ── 3. La course sur `nextid` ─────────────────────────────────────────────────

def test_creation_refusee_si_lidentifiant_a_ete_pris_entre_temps(
        client, admin_headers, monkeypatch):
    """
    `cluster/nextid` ne réserve rien : il constate. Entre sa réponse et la création,
    n'importe qui peut prendre le numéro depuis l'interface Proxmox — et le créneau
    atteignait dix minutes quand le téléchargement de l'ISO WinPE s'y trouvait.
    OSIRIS doit s'arrêter net, sans écrire ET sans nettoyer.
    """
    hv_id = _hyperviseur()
    appels: list = []

    async def fake_get(h, path):
        if path.endswith("/cluster/nextid"):
            return "150"
        if path.endswith("/config"):
            return config_vm_etrangere()     # 150 est DÉJÀ pris
        if path.endswith("/storage"):
            return [{"storage": "local-lvm", "type": "lvmthin", "active": 1,
                     "content": "images,rootdir"}]
        return {}

    async def fake_post(h, path, data=None):
        appels.append(path)
        return {}

    detruites: list = []

    async def fake_destroy(h, node, vm_id, nom_attendu=""):
        detruites.append(vm_id)

    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    monkeypatch.setattr(main, "_proxmox_post", fake_post)
    monkeypatch.setattr(main, "_destroy_vm_quietly", fake_destroy)

    resp = client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": "srv-neuf", "client": "Acme", "os": "ubuntu",
        "node": "pve", "storage": "local-lvm", "boot_mode": "pxe",
    })

    assert resp.status_code == 409, resp.text
    assert "déjà occupé" in resp.json()["detail"]
    assert not any(p.endswith("/qemu") for p in appels), "aucune VM ne devait être créée"
    assert detruites == [], "surtout : la VM du tiers ne devait pas être détruite"


def test_deux_fiches_ne_peuvent_pas_reserver_le_meme_identifiant(
        client, test_machine, admin_headers, monkeypatch):
    """
    La réservation qui manquait à `nextid`. Deux créations simultanées recevaient le
    même numéro : la première créait la VM, la seconde échouait sur « already
    exists », et son rollback purgeait la VM de la première.
    """
    hv_id = _hyperviseur()
    _vm(hv_id, vm_id=150)                     # 150 est déjà réservé par une fiche
    appels: list = []

    async def fake_get(h, path):
        if path.endswith("/cluster/nextid"):
            return "150"
        if path.endswith("/config"):
            raise main.HTTPException(status_code=502, detail="Proxmox 500: no such VM")
        return {}

    async def fake_post(h, path, data=None):
        appels.append(path)
        return {}

    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    monkeypatch.setattr(main, "_proxmox_post", fake_post)

    resp = client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": "srv-neuf", "client": "Acme", "os": "ubuntu",
        "node": "pve", "storage": "local-lvm", "boot_mode": "pxe",
    })

    assert resp.status_code == 409, resp.text
    assert appels == [], "l'échec doit précéder tout appel à l'hyperviseur"


def test_les_machines_physiques_echappent_a_la_reservation(client, admin_headers):
    """
    L'index de réservation est PARTIEL. Sans le `WHERE proxmox_vm_id > 0`, la
    deuxième machine physique — toutes portent 0 — serait refusée.
    """
    with Session(engine) as session:
        for i in range(3):
            session.add(Machine(mac=f"aabbccdd00{i:02d}", hostname=f"PC-{i}",
                                client="Acme", os="windows"))
        session.commit()
        assert len(session.exec(select(Machine)).all()) == 3


# ── 4. Le déclencheur non authentifié ────────────────────────────────────────

def test_pending_non_authentifie_est_refuse(client, test_machine, monkeypatch):
    """
    `/machines/{mac}/status` est sans authentification, et doit le rester : c'est la
    seule voix des machines en cours de déploiement. Mais `pending` ne rapporte
    rien — il DÉCLENCHE une réinstallation. Il suffisait d'atteindre OSIRIS et de
    connaître une MAC enregistrée pour faire effacer une machine.
    """
    _vm(_hyperviseur())
    vu = _proxmox(monkeypatch, config_vm_conforme())

    # Statut de départ non ambigu : la fiche de test naît « pending », ce qui
    # rendrait l'assertion finale vide de sens.
    with Session(engine) as session:
        m = session.exec(select(Machine).where(Machine.mac == MAC)).first()
        m.status = "deployed"
        session.add(m)
        session.commit()

    resp = client.post(f"/machines/{MAC}/status", params={"status": "pending"})

    assert resp.status_code == 401, resp.text
    assert vu["ecritures"] == [], "la VM ne devait pas être renvoyée sur son CD"
    with Session(engine) as session:
        m = session.exec(select(Machine).where(Machine.mac == MAC)).first()
    assert m.status == "deployed", "le statut ne devait pas changer"


@pytest.mark.parametrize("status", ["deploying", "deployed", "failed"])
def test_une_machine_rapporte_toujours_son_avancement_sans_jeton(
        client, test_machine, monkeypatch, status):
    """Le corollaire : fermer `pending` ne doit fermer aucun rapport légitime."""
    _proxmox(monkeypatch, config_vm_conforme())

    resp = client.post(f"/machines/{MAC}/status", params={"status": status})

    assert resp.status_code == 200, resp.text


def test_le_refus_de_redeploiement_est_journalise(client, test_machine):
    with Session(engine) as session:
        session.exec(select(Machine).where(Machine.mac == MAC)).first()

    client.post(f"/machines/{MAC}/status", params={"status": "pending"})

    with Session(engine) as session:
        trace = session.exec(
            select(AuditLog).where(AuditLog.action == "redeploiement_refuse")).first()
    assert trace is not None
    assert trace.target_mac == MAC


# ── 5. Le pool : bornage du rayon d'action côté hyperviseur ──────────────────

def test_les_vm_creees_sont_rangees_dans_le_pool_declare(client, admin_headers, monkeypatch):
    """
    Ranger les VM d'OSIRIS dans un pool est ce qui permet de n'attribuer au jeton
    que des droits sur `/pool/<pool>` au lieu de `/`. Sans ça, le jeton garde droit
    de vie et de mort sur TOUTES les VM du cluster, y compris celles d'OSIRIS.
    """
    hv_id = _hyperviseur(pool="osiris")
    captures: dict = {}

    async def fake_get(h, path):
        if path.endswith("/cluster/nextid"):
            return "150"
        if path.endswith("/config"):
            raise main.HTTPException(status_code=502, detail="Proxmox 500: no such VM")
        if path.endswith("/storage"):
            return [{"storage": "local-lvm", "type": "lvmthin", "active": 1,
                     "content": "images,rootdir"}]
        return {}

    async def fake_post(h, path, data=None):
        if path.endswith("/qemu"):
            captures["qemu"] = data
        return {}

    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    monkeypatch.setattr(main, "_proxmox_post", fake_post)

    resp = client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": "srv-neuf", "client": "Acme", "os": "ubuntu",
        "node": "pve", "storage": "local-lvm", "boot_mode": "pxe",
    })

    assert resp.status_code == 201, resp.text
    assert captures["qemu"]["pool"] == "osiris"


def test_sans_pool_declare_rien_ne_change(client, admin_headers, monkeypatch):
    """Le pool est facultatif : une installation existante ne doit pas être cassée."""
    hv_id = _hyperviseur(pool="")
    captures: dict = {}

    async def fake_get(h, path):
        if path.endswith("/cluster/nextid"):
            return "150"
        if path.endswith("/config"):
            raise main.HTTPException(status_code=502, detail="Proxmox 500: no such VM")
        if path.endswith("/storage"):
            return [{"storage": "local-lvm", "type": "lvmthin", "active": 1,
                     "content": "images,rootdir"}]
        return {}

    async def fake_post(h, path, data=None):
        if path.endswith("/qemu"):
            captures["qemu"] = data
        return {}

    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    monkeypatch.setattr(main, "_proxmox_post", fake_post)

    client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": "srv-neuf", "client": "Acme", "os": "ubuntu",
        "node": "pve", "storage": "local-lvm", "boot_mode": "pxe",
    })

    assert "pool" not in captures.get("qemu", {})


# ── 6. TLS ───────────────────────────────────────────────────────────────────

def test_un_hyperviseur_neuf_verifie_le_certificat_par_defaut(client, admin_headers):
    """
    Le jeton peut détruire des VM : il n'a rien à faire sur une session
    interceptable. La vérification reste désactivable, mais c'est alors un choix
    explicite — plus le défaut silencieux.
    """
    resp = client.post("/hypervisors", headers=admin_headers, json={
        "name": "pve-neuf", "url": "https://pve.test:8006",
        "token_id": "root@pam!osiris", "token_secret": "s3cret",
    })
    assert resp.status_code in (200, 201), resp.text
    assert resp.json()["tls_verify"] is True


# ── 7. Le message du conflit de réservation nomme la VRAIE cause ─────────────

def test_une_fiche_perimee_est_nommee_et_son_sort_precise(client, test_machine,
                                                          admin_headers, monkeypatch):
    """
    Rencontré le 2026-08-14. Une VM supprimée dans l'interface de l'hyperviseur
    laisse sa fiche derrière elle ; `nextid` repropose le numéro, la réservation
    le refuse, et le message accusait « un déploiement simultané » — ce que
    l'opérateur n'avait pas fait. Il faut nommer la fiche fautive et dire que sa
    VM a disparu, sinon on cherche un conflit qui n'existe pas.
    """
    hv_id = _hyperviseur()
    _vm(hv_id, vm_id=150)                       # la fiche retient le 150

    async def fake_get(h, path):
        if path.endswith("/cluster/nextid"):
            return "150"
        if path.endswith("/config"):
            # la VM du 150 n'existe plus : supprimée hors d'OSIRIS
            raise main.HTTPException(status_code=502, detail="Proxmox 500: no such VM")
        return {}

    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    monkeypatch.setattr(main, "_proxmox_post", lambda *a, **k: None)

    resp = client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": "srv-neuf", "client": "Acme", "os": "ubuntu",
        "node": "pve", "storage": "local-lvm", "boot_mode": "pxe",
    })

    assert resp.status_code == 409, resp.text
    d = resp.json()["detail"]
    assert "PC-TEST" in d, "la fiche fautive doit être nommée"
    assert "n'existe plus" in d, "il faut dire que la VM a disparu"
    assert "Retirer la fiche" in d, "et quoi faire ensuite"
    assert "simultané" not in d, "ce n'est PAS la cause ici"


def test_un_vrai_conflit_reste_annonce_comme_tel(client, test_machine,
                                                 admin_headers, monkeypatch):
    """Le corollaire : quand la VM existe encore, c'est bien un numéro déjà pris."""
    hv_id = _hyperviseur()
    _vm(hv_id, vm_id=150)

    async def fake_get(h, path):
        if path.endswith("/cluster/nextid"):
            return "150"
        if path.endswith("/config"):
            return config_vm_conforme()          # la VM est bien là
        return {}

    monkeypatch.setattr(main, "_proxmox_get", fake_get)
    monkeypatch.setattr(main, "_proxmox_post", lambda *a, **k: None)

    resp = client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": "srv-neuf", "client": "Acme", "os": "ubuntu",
        "node": "pve", "storage": "local-lvm", "boot_mode": "pxe",
    })

    assert resp.status_code == 409, resp.text
    d = resp.json()["detail"]
    assert "existe toujours" in d
    assert "Retirer la fiche" not in d, "surtout pas : la VM tourne"
