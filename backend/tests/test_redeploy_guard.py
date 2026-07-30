# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Garde-fou : une machine déjà déployée ne doit jamais recevoir de script WinPE.

Scénario réel rencontré sur un lot de 3 portables déployés d'affilée : la protection
de la route `/boot` ne s'arme que si la MAC vue sur le fil est celle de la fiche.
Avec un adaptateur USB-Ethernet ou l'option Dell « MAC Address Pass Through », ce
n'est pas le cas — WinPE démarre alors par le repli « un déploiement est en attente »,
identifie la machine par son numéro de série, et sans ce test se ferait servir un
script qui repartitionne le disque d'un poste déjà en production.
"""
import pytest
from sqlmodel import Session, SQLModel, create_engine

import main
from models import Machine, OsImage


@pytest.fixture
def session(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(OsImage(name="Windows 11", os="windows", version="11",
                      status="ready", iso_url=""))
        for mac, hostname, status in [
            ("02aabbcc0098", "PC098", "deployed"),
            ("02aabbcc0099", "PC099", "pending"),
            ("02aabbcc0100", "PC100", "deploying"),
            ("02aabbcc0101", "PC101", "failed"),
        ]:
            s.add(Machine(mac=mac, hostname=hostname, status=status,
                          client="ACME", os="windows", ou="", hw_serial=f"SN{hostname}"))
        s.commit()
    monkeypatch.setattr(main, "engine", engine)
    return engine


def test_machine_deployee_refusee(session):
    resp = main._build_winpe_script("02aabbcc0098")
    body = resp.body.decode()
    assert "DEPLOIEMENT REFUSE" in body
    assert "PC098" in body
    assert "exit /b 1" in body


def test_le_refus_ne_contient_aucune_commande_destructrice(session):
    """Le script refusé ne doit rien pouvoir faire au disque."""
    body = main._build_winpe_script("02aabbcc0098").body.decode().lower()
    for danger in ("diskpart", "format", "dism", "clean", "create partition"):
        assert danger not in body


def test_le_refus_est_servi_en_200(session):
    """`curl -sf` de startnet jette le corps d'une reponse >= 400 : l'operateur
    verrait alors le script generique « machine non reconnue », message trompeur."""
    assert main._build_winpe_script("02aabbcc0098").status_code == 200


@pytest.mark.parametrize("mac,hostname", [
    ("02aabbcc0099", "PC099"),   # pending : cas du repli par numero de serie
    ("02aabbcc0100", "PC100"),   # deploying : flux normal, /boot a deja bascule le statut
    ("02aabbcc0101", "PC101"),   # failed : on doit pouvoir retenter
])
def test_les_autres_statuts_recoivent_bien_le_script_de_deploiement(session, mac, hostname):
    body = main._build_winpe_script(mac).body.decode()
    assert "DEPLOIEMENT REFUSE" not in body
    assert "diskpart" in body.lower()


def test_machine_inconnue_toujours_en_404(session):
    resp = main._build_winpe_script("aabbccddeeff")
    assert resp.status_code == 404
    assert "inconnue" in resp.body.decode()
