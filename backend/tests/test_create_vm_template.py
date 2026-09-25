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
    # Numeros deja pris sur le faux hyperviseur. Vide au depart : le 150 que rend
    # `nextid` doit etre vu comme LIBRE, sinon OSIRIS refuse de provisionner —
    # c'est precisement le controle qui empeche d'ecrire sur la VM d'un tiers.
    clones: set = set()

    async def fake_get(h, path):
        if path.endswith("/cluster/nextid"):
            return "150"
        if "type=vm" in path:
            # OSIRIS demande desormais OU vit le template : la configuration d'une VM
            # appartient a un noeud, son disque au stockage. Le clone doit etre
            # adresse au noeud qui detient la configuration.
            return [{"vmid": 100, "name": "SRV-WIN-TPL", "node": "pve", "template": 1,
                     "status": "stopped", "maxcpu": 4, "maxmem": 4294967296},
                    {"vmid": 9001, "name": "ubuntu-osiris", "node": "pve", "template": 1,
                     "status": "stopped", "maxcpu": 2, "maxmem": 2147483648}]
        if path.endswith("/config"):
            vmid = int(path.split("/qemu/")[1].split("/")[0])
            if vmid not in clones:
                raise main.HTTPException(status_code=502,
                                         detail="Proxmox 500: Configuration file does not exist")
            # Config du clone, lue par _agrandir_disque_si_besoin et par le
            # controle d'identite (nom + UUID SMBIOS).
            return {"name": captured.get("nom_attendu", "SRV-CLONE"),
                    "smbios1": "uuid=00000000-0000-4000-8000-000000000150",
                    "sata0": f"Lab_CEPH:vm-150-disk-1,size={disque_template_gb}G",
                    "scsi0": f"Lab_CEPH:vm-150-disk-0,size={disque_template_gb}G"}
        return {}

    async def fake_post(h, path, data=None):
        if path.endswith("/clone"):
            captured["clone_path"] = path
            captured["clone"] = data
            clones.add(int(data["newid"]))          # le clone existe desormais
            captured["nom_attendu"] = data.get("name", "SRV-CLONE")
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


# ── Le journal s'ouvre à la création ──────────────────────────────────────────
# Une VM dont l'agent ne rappelle jamais laissait un journal totalement VIDE :
# ni erreur, ni ligne, rien à montrer. C'est ce qu'on a lu le 25/08, et c'est ce
# qui a fait conclure « OSIRIS n'a rien fait » alors qu'il avait tout fait.
# Une seule ligne suffit à transformer « aucune trace » en « créée à telle heure,
# puis plus rien » — qui, lui, se diagnostique.

def _journal(mac: str) -> list[str]:
    from sqlmodel import select
    from models import DeployLogLine
    with Session(engine) as session:
        return [l.line for l in session.exec(
            select(DeployLogLine).where(DeployLogLine.mac == mac)
            .order_by(DeployLogLine.id)).all()]


def test_la_creation_ouvre_le_journal(client, admin_headers, monkeypatch):
    hv = _make_hypervisor()
    _patch(monkeypatch, {})

    r = client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers, json=_corps())
    assert r.status_code == 201, r.text

    lignes = _journal(r.json()["mac"])
    assert len(lignes) == 1, "une VM créée doit laisser une trace, même si elle ne rappelle jamais"
    assert "en attente du premier rappel" in lignes[0]


def test_le_journal_nomme_l_hyperviseur_et_le_mode(client, admin_headers, monkeypatch):
    """Sans ces deux repères, la ligne ne vaut pas mieux qu'un journal vide."""
    hv = _make_hypervisor()
    _patch(monkeypatch, {})

    r = client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers, json=_corps())
    ligne = _journal(r.json()["mac"])[0]
    assert "pve-test" in ligne          # quel hyperviseur
    assert "template" in ligne          # quel mode d'amorçage
    assert "150" in ligne               # quel identifiant de VM


def test_la_ligne_est_ecrite_sous_la_MAC_ATTRIBUEE_par_l_hyperviseur(
        client, admin_headers, monkeypatch):
    """Sur vSphere, la MAC du clone est décidée par la plateforme, pas par OSIRIS.

    Le journal est indexé sur la MAC. Écrire la ligne avant la bascule la
    rattacherait à la MAC provisoire — donc à une machine qui n'existe pas, et le
    journal de la vraie VM resterait vide. C'est précisément le piège que cette
    ligne est censée fermer.
    """
    hv = _make_hypervisor()
    _patch(monkeypatch, {})
    MAC_FINALE = "005056aa0042"

    class ProviderQuiReattribueLaMac:
        @staticmethod
        async def next_vm_id(h):
            return 0

        @staticmethod
        def generate_mac():
            return "00505600beef"          # MAC provisoire, jetée par le clone

        @staticmethod
        async def provision_vm(h, body, vm_id, mac_colons, mac_plain, user_data, render, jeton=""):
            return {"vm_id": 259107, "mac": MAC_FINALE,
                    "vm_uuid": "42010000-0000-4000-8000-000000000001"}

        @staticmethod
        async def destroy_vm(h, node, vm_id, nom_attendu=""):
            return None

    monkeypatch.setattr(main, "_provider", lambda h: ProviderQuiReattribueLaMac)

    r = client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers, json=_corps())
    assert r.status_code == 201, r.text
    assert r.json()["mac"] == MAC_FINALE

    assert _journal("00505600beef") == [], "rien ne doit rester sous la MAC provisoire"
    assert len(_journal(MAC_FINALE)) == 1, "le journal suit la MAC réellement attribuée"


# ── Un clone nu ne peut pas recevoir d'adresse fixe sur Proxmox ──────────────
# Sur vSphere, `guestinfo` sert de canal et l'agent gravé le lit. Sur Proxmox il
# n'existe aucun équivalent : l'adresse saisie était simplement PERDUE. La VM
# démarrait en DHCP — ou sans rien du tout sur un VLAN qui n'en a pas — et
# restait muette, sans qu'aucune erreur ne soit jamais levée.

def test_une_adresse_fixe_en_clone_nu_proxmox_est_REFUSEE(client, admin_headers, monkeypatch):
    hv = _make_hypervisor()
    cap: dict = {}
    _patch(monkeypatch, cap)

    r = client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers,
                    json=_corps(ip_cidr="10.0.5.20/24", gateway="10.0.5.1",
                                dns_servers="10.0.5.110"))
    assert r.status_code == 400, r.text
    assert "clone nu" in r.json()["detail"]
    assert "cloud-init" in r.json()["detail"], "le refus doit dire QUOI faire à la place"
    assert "clone" not in cap, "rien ne doit être créé sur l'hyperviseur"


def test_le_refus_arrive_AVANT_le_moindre_appel_a_l_hyperviseur(client, admin_headers, monkeypatch):
    """Un refus tardif coûterait un clone puis une destruction — et c'est
    précisément la séquence qui a déjà purgé la VM d'un tiers."""
    hv = _make_hypervisor()
    cap: dict = {}
    _patch(monkeypatch, cap)

    client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers,
                json=_corps(ip_cidr="10.0.5.20/24", gateway="10.0.5.1",
                            dns_servers="10.0.5.110"))
    assert cap == {}, f"aucun appel ne devait partir, or : {sorted(cap)}"


def test_sans_adresse_le_clone_nu_proxmox_passe_toujours(client, admin_headers, monkeypatch):
    """Le clone nu reste parfaitement légitime : on refuse la prétention à
    imposer une adresse, pas le mode lui-même."""
    hv = _make_hypervisor()
    _patch(monkeypatch, {})
    r = client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers, json=_corps())
    assert r.status_code == 201, r.text
