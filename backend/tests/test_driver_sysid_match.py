# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Tests du rapprochement pack de pilotes ↔ identifiant matériel.

Le nom commercial ne suffit pas à désigner une machine : un ThinkPad **T15**
(Machine Type 20S6/20S7) et un ThinkPad **T15g** (20UR/20US) sont deux machines
différentes que sépare une seule lettre. Le 2026-07-16, le T15g a effectivement
été assigné à un T15 — d'où le rapprochement par identifiant constructeur.
"""
import pytest
from sqlmodel import Session, SQLModel, create_engine

import main
from models import DriverPack
from worker import _hw_ids


# ── Normalisation des identifiants du catalogue ────────────────────────────

@pytest.mark.parametrize("brut,attendu", [
    (["20S6", "20S7"],       "20s6,20s7"),   # Lenovo : liste de Machine Types
    (["81c3,8396"],          "81c3,8396"),   # HP : SystemId séparés par virgule
    (["092F"],               "092f"),        # Dell : systemID seul
    (["20S7", "20S6"],       "20s6,20s7"),   # trié : comparaison stable
    (["20S6", "20s6"],       "20s6"),        # dédoublonné malgré la casse
    ([" 20S6 ", "", None],   "20s6"),        # espaces et valeurs vides ignorés
    ([],                     ""),
])
def test_hw_ids_normalise(brut, attendu):
    assert _hw_ids(brut) == attendu


# ── Résolution d'un pack depuis l'identifiant remonté par la machine ───────

@pytest.fixture
def session(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add_all([
            DriverPack(vendor="lenovo", model="ThinkPad T15 Type 20S6 20S7",
                       model_key="thinkpadt15type20s620s7", os_code="Windows11",
                       download_url="http://x/t15", status="ready",
                       local_path="/srv/data/windows/drivers/lenovo/t15",
                       hw_ids="20s6,20s7"),
            DriverPack(vendor="lenovo", model="ThinkPad T15G Gen 1 Type 20UR 20US",
                       model_key="thinkpadt15ggen1type20ur20us", os_code="Windows11",
                       download_url="http://x/t15g", status="ready",
                       local_path="/srv/data/windows/drivers/lenovo/t15g",
                       hw_ids="20ur,20us"),
            DriverPack(vendor="hp", model="EliteBook 650 G10", model_key="elitebook650g10",
                       os_code="Windows11", download_url="http://x/hp", status="ready",
                       local_path="/srv/data/windows/drivers/hp/eb650g10",
                       hw_ids="8b42,8b43"),
            # Pack non téléchargé : ne doit jamais être proposé à l'injection
            DriverPack(vendor="lenovo", model="ThinkPad X1 Type 20XW",
                       model_key="thinkpadx1type20xw", os_code="Windows11",
                       download_url="http://x/x1", status="available", hw_ids="20xw"),
        ])
        s.commit()
        yield s


def test_le_mtm_designe_le_t15_et_pas_le_t15g(session):
    """Le cœur du piège : ces deux MTM ne diffèrent qu'au 3e caractère."""
    assert _model(main._pack_for_sysid(session, "20S6CTO1WW")) == "ThinkPad T15 Type 20S6 20S7"
    assert _model(main._pack_for_sysid(session, "20URCTO1WW")) == "ThinkPad T15G Gen 1 Type 20UR 20US"


def test_identifiant_exact_sans_suffixe(session):
    """Dell/HP remontent l'identifiant seul, sans suffixe de configuration."""
    assert _model(main._pack_for_sysid(session, "8b42")) == "EliteBook 650 G10"


def test_casse_indifferente(session):
    assert _model(main._pack_for_sysid(session, "20s6cto1ww")) == "ThinkPad T15 Type 20S6 20S7"


@pytest.mark.parametrize("sysid", ["", "   ", "INCONNU", "9999XYZ"])
def test_identifiant_absent_ou_inconnu_ne_renvoie_rien(session, sysid):
    assert main._pack_for_sysid(session, sysid) is None


def test_un_pack_non_telecharge_n_est_jamais_propose(session):
    """20XW existe au catalogue mais n'est pas sur le disque : l'injecter
    donnerait un chemin vide, pire que le repli sur le dossier complet."""
    assert main._pack_for_sysid(session, "20XWCTO1WW") is None


def _model(pack):
    return pack.model if pack else None
