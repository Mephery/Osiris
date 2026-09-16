# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Une VM créée qui ne rappelle jamais ne doit plus passer inaperçue.

Le mode de panne visé est le plus désagréable de tous : la création RÉUSSIT.
L'hyperviseur crée la VM, OSIRIS relit la MAC attribuée, la fiche est correcte,
l'API rend 201 — puis l'agent gravé dans le gabarit n'arrive pas à se lire son
adresse, la machine part en APIPA, et plus rien ne se produit. Aucun évènement,
aucune erreur, aucune ligne de journal. La fiche reste « pending » exactement
comme une fiche créée à l'instant.

C'est ce qui est arrivé le 25/08 : personne n'a rien vu pendant deux semaines.
Ces tests vérifient qu'OSIRIS nomme désormais cet état au lieu de le taire.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session as _S

import main
from models import engine, Hypervisor, Machine


def Session(bind):
    return _S(bind, expire_on_commit=False)


@pytest.fixture
def hyperviseur(clean_db):
    with Session(engine) as s:
        h = Hypervisor(name="vCenter de test", type="vsphere",
                       url="https://vcenter.test", token_id="osiris@vsphere.local",
                       token_secret="", tls_verify=False)
        s.add(h)
        s.commit()
        s.refresh(h)
        return h


def _fiche(hv_id, *, statut="pending", age_minutes=0, mac="005056000001"):
    """Pose une fiche dont on choisit l'âge et l'état."""
    with Session(engine) as s:
        m = Machine(
            mac=mac, hostname="vm-test", client="Test", os="windows", ou="",
            status=statut, hypervisor_id=hv_id, proxmox_vm_id=1234,
            hw_serial="", hw_model="", hw_ram_gb=0, bitlocker_key="",
            bitlocker_pin="", laps_password="", user_name="", user_email="",
            notes="", smoke_status="", smoke_results="",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=age_minutes),
        )
        s.add(m)
        s.commit()
        return m


def test_une_fiche_toute_neuve_n_est_pas_muette(hyperviseur):
    """Un clone a le droit de mettre quelques minutes à rappeler."""
    _fiche(hyperviseur.id, age_minutes=0)
    assert main.deploiements_muets() == 0


def test_une_fiche_pending_depuis_trop_longtemps_est_muette(hyperviseur):
    _fiche(hyperviseur.id, age_minutes=main.DEPLOIEMENT_MUET_MINUTES + 1)
    assert main.deploiements_muets() == 1


def test_le_seuil_tranche_exactement(hyperviseur):
    """Le compte se fait sur le seuil demandé, pas sur une constante figée."""
    _fiche(hyperviseur.id, age_minutes=45)
    assert main.deploiements_muets(seuil_minutes=60) == 0
    assert main.deploiements_muets(seuil_minutes=30) == 1


def test_une_machine_deployee_n_est_jamais_muette(hyperviseur):
    """Le silence ne compte que tant que la machine n'a pas rappelé."""
    _fiche(hyperviseur.id, statut="deployed", age_minutes=10_000)
    assert main.deploiements_muets() == 0


def test_une_machine_PHYSIQUE_en_attente_n_est_pas_comptee(clean_db):
    """Un poste physique peut légitimement attendre des jours qu'on l'allume.

    Une VM, elle, a été démarrée par OSIRIS à l'instant même de sa création :
    c'est ce qui rend son silence anormal. Confondre les deux noierait l'alerte
    sous les machines qui attendent simplement leur tour sur une étagère.
    """
    with Session(engine) as s:
        s.add(Machine(
            mac="aabbccddeeff", hostname="PC-PHYSIQUE", client="Test", os="windows",
            ou="", status="pending", hypervisor_id=None, proxmox_vm_id=0,
            hw_serial="", hw_model="", hw_ram_gb=0, bitlocker_key="",
            bitlocker_pin="", laps_password="", user_name="", user_email="",
            notes="", smoke_status="", smoke_results="",
            created_at=datetime.now(timezone.utc) - timedelta(days=30),
        ))
        s.commit()
    assert main.deploiements_muets() == 0


def test_health_expose_le_compteur(client, hyperviseur):
    _fiche(hyperviseur.id, age_minutes=main.DEPLOIEMENT_MUET_MINUTES + 1)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["deploiements_muets"] == 1


def test_health_ne_nomme_AUCUNE_machine(client, hyperviseur):
    """`/health` n'est pas authentifié : il rend un nombre, pas un inventaire."""
    _fiche(hyperviseur.id, age_minutes=10_000, mac="005056ffffff")
    corps = client.get("/health").text
    assert "vm-test" not in corps
    assert "005056ffffff" not in corps


def test_des_vm_muettes_ne_rendent_pas_le_service_degrade(client, hyperviseur):
    """Une alerte n'est pas une indisponibilité — même distinction que `winpe`."""
    _fiche(hyperviseur.id, age_minutes=10_000)
    assert client.get("/health").json()["status"] == "ok"
