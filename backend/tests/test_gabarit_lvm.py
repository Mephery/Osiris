# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Clone d'un gabarit LVM : UN disque, découpé au premier démarrage.

Le gabarit déclaré LVM (à la main, Infrastructure › Gabarits) se clone en un seul
disque dont la taille est la somme du schéma — /boot, swap, « / », volumes. Les
volumes deviennent des LV du groupe « osiris » : l'hyperviseur n'en crée aucun.
Les tailles voyagent par la fiche jusqu'au premier démarrage, qui les applique.

L'invariant surveillé (cf. « champs décoratifs ») : une taille saisie est soit
APPLIQUÉE, soit REFUSÉE — jamais ignorée en silence.
"""
import json

import pytest
from sqlmodel import Session, select

import main
from disques import schema_partition
from models import engine, GabaritOsiris, Machine
from tests.test_create_vm_template import _corps, _make_hypervisor, _patch

UUID = "4210aaaa-bbbb-cccc-dddd-eeeeffff0001"
VOLUME = {"taille_gb": 50, "point_montage": "/var/lib/mysql", "libelle": "mysql",
          "lvm": True, "systeme_fichiers": "xfs"}


def _gabarit(monkeypatch, *, lvm: bool):
    """Le gabarit 9001 annoté comme OSIRIS, LVM ou non. État « inconnu » : la
    fiche n'exige pas de jeton, le premier démarrage se lit sans."""
    def annoter(modeles):
        for m in modeles:
            m["distribution"] = ""
            m["osiris"] = ({"etat": "inconnu", "os": "linux", "lvm": lvm}
                           if int(m["vmid"]) == 9001 else None)
        return modeles
    monkeypatch.setattr(main, "_annoter_gabarits", annoter)


def _corps_linux(**o):
    base = dict(os="debian", hostname="srv-lvm", template_id=9001, disk_gb=20)
    base.update(o)
    return _corps(**base)


def _fiche(hostname="srv-lvm") -> Machine:
    with Session(engine) as s:
        return s.exec(select(Machine).where(Machine.hostname == hostname)).first()


# ── Création ──────────────────────────────────────────────────────────────────

def test_un_clone_lvm_recoit_un_seul_disque_a_la_taille_du_schema(client, admin_headers, monkeypatch):
    hv = _make_hypervisor()
    cap: dict = {}
    _patch(monkeypatch, cap, disque_template_gb=16)
    _gabarit(monkeypatch, lvm=True)

    r = client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers,
                    json=_corps_linux(root_gb=40, swap_gb=4, disques=[VOLUME]))
    assert r.status_code == 201, r.text

    total = schema_partition(40, 4, [VOLUME])["total_gb"]      # 0,5 + 1 + 4 + 40 + 50
    assert total == 96
    assert cap["resize"] == {"disk": "scsi0", "size": f"{total}G"}
    # Aucun disque séparé : le volume est un LV du disque système
    assert not any(k.startswith("scsi") and k != "scsi0" for k in cap["config"])

    m = _fiche()
    assert (m.root_gb, m.swap_gb) == (40, 4)
    assert json.loads(m.disques)[0]["point_montage"] == "/var/lib/mysql"


def test_le_premier_demarrage_applique_les_tailles_de_la_fiche(client, admin_headers, monkeypatch):
    hv = _make_hypervisor()
    _patch(monkeypatch, {}, disque_template_gb=16)
    _gabarit(monkeypatch, lvm=True)
    client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers,
                json=_corps_linux(root_gb=40, swap_gb=4, disques=[VOLUME]))
    monkeypatch.setattr(main, "_exiger_fenetre_de_deploiement", lambda *a: None)

    script = client.get(f"/firstboot-debian/{_fiche().mac}").text
    assert "lvextend -r -L 40G" in script
    assert "lvcreate -y -L 4G -n swap" in script
    assert "_preparer_lv 'mysql' 50 '/var/lib/mysql' 'xfs'" in script


def test_un_gabarit_classique_garde_ses_disques_separes(client, admin_headers, monkeypatch):
    hv = _make_hypervisor()
    cap: dict = {}
    _patch(monkeypatch, cap, disque_template_gb=16)
    _gabarit(monkeypatch, lvm=False)

    r = client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers,
                    json=_corps_linux(disk_gb=30, disques=[VOLUME]))
    assert r.status_code == 201, r.text
    assert cap["resize"] == {"disk": "scsi0", "size": "30G"}     # disk_gb = disque système
    assert any(k.startswith("scsi") and k != "scsi0" for k in cap["config"])
    assert _fiche().root_gb is None                             # « / » n'est pas touché


def test_une_taille_de_racine_sur_un_gabarit_classique_est_refusee(client, admin_headers, monkeypatch):
    """Elle ne serait appliquée par personne : refus AVANT le clone."""
    hv = _make_hypervisor()
    cap: dict = {}
    _patch(monkeypatch, cap)
    _gabarit(monkeypatch, lvm=False)

    r = client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers,
                    json=_corps_linux(root_gb=40))
    assert r.status_code == 409
    assert "pas déclaré LVM" in r.json()["detail"]
    assert "clone" not in cap and _fiche() is None


def test_un_gabarit_lvm_exige_la_taille_de_racine(client, admin_headers, monkeypatch):
    hv = _make_hypervisor()
    cap: dict = {}
    _patch(monkeypatch, cap)
    _gabarit(monkeypatch, lvm=True)

    r = client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers, json=_corps_linux())
    assert r.status_code == 422
    assert "clone" not in cap


def test_une_racine_trop_petite_est_refusee_avant_le_clone(client, admin_headers, monkeypatch):
    hv = _make_hypervisor()
    cap: dict = {}
    _patch(monkeypatch, cap)
    _gabarit(monkeypatch, lvm=True)

    r = client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers,
                    json=_corps_linux(root_gb=5))
    assert r.status_code == 422 and "clone" not in cap


def test_le_client_ne_peut_pas_imposer_le_mode_lvm(client, admin_headers, monkeypatch):
    """`_lvm` est décidé par le serveur : envoyé dans le JSON, il est ignoré, et
    les disques restent séparés sur un gabarit classique."""
    hv = _make_hypervisor()
    cap: dict = {}
    _patch(monkeypatch, cap, disque_template_gb=16)
    _gabarit(monkeypatch, lvm=False)

    r = client.post(f"/hypervisors/{hv}/create-vm", headers=admin_headers,
                    json={**_corps_linux(disques=[VOLUME]), "_lvm": True})
    assert r.status_code == 201, r.text
    assert any(k.startswith("scsi") and k != "scsi0" for k in cap["config"])


def test_disques_hyperviseur_vide_pour_un_clone_lvm():
    body = main.VmCreateBody(**_corps_linux(root_gb=40, disques=[VOLUME]))
    assert main.disques_hyperviseur(body)[0]["taille_gb"] == 50
    body._lvm = True
    assert main.disques_hyperviseur(body) == []


# ── Déclaration du gabarit ────────────────────────────────────────────────────

@pytest.fixture
def modele(monkeypatch):
    async def uuid_du_modele(h, vmid):
        return UUID
    monkeypatch.setattr(main, "_uuid_du_modele", uuid_du_modele)
    return _make_hypervisor()


def test_declarer_lvm_exige_un_gabarit_osiris(client, admin_headers, modele):
    r = client.put(f"/hypervisors/{modele}/templates/9001/osiris/lvm",
                   headers=admin_headers, json={"lvm": True})
    assert r.status_code == 409


def test_declarer_puis_retirer_lvm(client, admin_headers, modele):
    with Session(engine) as s:
        s.add(GabaritOsiris(uuid=UUID, os="linux"))
        s.commit()
    url = f"/hypervisors/{modele}/templates/9001/osiris/lvm"
    assert client.put(url, headers=admin_headers, json={"lvm": True}).status_code == 204
    annote = main._annoter_gabarits([{"vmid": 9001, "name": "debian-lvm", "uuid": UUID}])
    assert annote[0]["osiris"]["lvm"] is True
    assert client.put(url, headers=admin_headers, json={"lvm": False}).status_code == 204
    with Session(engine) as s:
        assert s.exec(select(GabaritOsiris).where(GabaritOsiris.uuid == UUID)).first().lvm is False


def test_un_gabarit_windows_ne_se_declare_pas_lvm(client, admin_headers, modele):
    with Session(engine) as s:
        s.add(GabaritOsiris(uuid=UUID, os="windows"))
        s.commit()
    r = client.put(f"/hypervisors/{modele}/templates/9001/osiris/lvm",
                   headers=admin_headers, json={"lvm": True})
    assert r.status_code == 422


def test_declarer_lvm_est_reserve_aux_administrateurs(client, modele):
    r = client.put(f"/hypervisors/{modele}/templates/9001/osiris/lvm", json={"lvm": True})
    assert r.status_code in (401, 403)


def test_le_firstboot_embarque_en_cloud_init_porte_aussi_les_tailles():
    """Chemin cloud-init : le script voyage DANS le user-data, rendu depuis la
    requête et non depuis la fiche. Mêmes tailles, même découpage."""
    import base64
    import re
    from models import Hypervisor
    body = main.VmCreateBody(**_corps_linux(boot_mode="cloudinit", root_gb=40,
                                            swap_gb=4, disques=[VOLUME]))
    body._lvm = True
    ud = main._render_cloud_init_user_data(Hypervisor(name="pve", url="https://pve.test"),
                                           body, "aabbccddeeff")
    b64 = re.search(r"[A-Za-z0-9+/=]{200,}", ud).group(0)
    script = base64.b64decode(b64).decode()
    assert "lvextend -r -L 40G" in script and "_preparer_lv 'mysql' 50" in script
