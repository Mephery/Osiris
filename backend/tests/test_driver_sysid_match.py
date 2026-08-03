# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Tests du rapprochement pack de pilotes ↔ identifiant matériel.

Le nom commercial ne suffit pas à désigner une machine : un ThinkPad **T15**
(Machine Type 20S6/20S7) et un ThinkPad **T15g** (20UR/20US) sont deux machines
différentes que sépare une seule lettre. Le 2026-07-16, le T15g a effectivement
été assigné à un T15 — d'où le rapprochement par identifiant constructeur.
"""
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

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


# ── Repli par nom commercial (Dell / HP) ───────────────────────────────────
# Chez Dell et HP, `hw_ids` contient un CODE ("0cf9") alors que la machine remonte
# son NOM ("Dell Pro 14 Plus PB14250") : les deux ne se rencontrent jamais. Sans ce
# repli, toute fiche Dell/HP sans pack choisi à la main se voyait injecter les ~36 Go
# du dossier `drivers/` entier — constaté le 30/07 sur les Dell Pro 14 Plus.

@pytest.fixture
def session_dell(session):
    session.add(DriverPack(vendor="dell", model="Dell Pro 14 Plus PB14250",
                           model_key="dellpro14pluspb14250", os_code="Windows11",
                           download_url="http://x/pb14250", status="ready",
                           local_path="/srv/data/windows/drivers/dell/dellpro14pluspb14250",
                           hw_ids="0cf9"))
    # Même modèle en Windows 10, téléchargé lui aussi : Windows 11 doit primer.
    session.add(DriverPack(vendor="dell", model="Dell Pro 14 Plus PB14250",
                           model_key="dellpro14pluspb14250", os_code="Windows10",
                           download_url="http://x/pb14250w10", status="ready",
                           local_path="/srv/data/windows/drivers/dell/pb14250w10",
                           hw_ids="0cf9"))
    session.commit()
    return session


def test_le_nom_commercial_dell_designe_le_bon_pack(session_dell):
    pack = main._pack_for_model_name(session_dell, "Dell Pro 14 Plus PB14250")
    assert _model(pack) == "Dell Pro 14 Plus PB14250"
    assert pack.os_code == "Windows11"       # préféré au pack Windows 10


def test_le_nom_est_insensible_a_la_casse_et_aux_espaces(session_dell):
    assert _model(main._pack_for_model_name(session_dell, "dell pro 14 plus PB14250")) \
        == "Dell Pro 14 Plus PB14250"


def test_un_nom_plus_long_que_le_catalogue_matche(session_dell):
    """Le catalogue est parfois plus court que ce que remonte la machine."""
    assert _model(main._pack_for_model_name(session_dell, "EliteBook 650 G10 Notebook PC")) \
        == "EliteBook 650 G10"


@pytest.mark.parametrize("nom", [
    "",                                # jamais renseigné
    "PC",                              # trop court pour discriminer
    "Standard PC (Q35 + ICH9, 2009)",  # VM QEMU : ne doit RIEN matcher
    "OptiPlex 7090",                   # absent du catalogue de test
])
def test_un_nom_inconnu_ou_trop_court_ne_matche_rien(session_dell, nom):
    assert main._pack_for_model_name(session_dell, nom) is None


def test_un_pack_non_telecharge_n_est_pas_propose_par_le_nom(session_dell):
    assert main._pack_for_model_name(session_dell, "ThinkPad X1 Type 20XW") is None


def test_le_nom_ne_prime_jamais_sur_l_identifiant_materiel(session_dell):
    """L'identifiant reste le critère fort : c'est lui qui sépare T15 et T15g."""
    assert _model(main._pack_for_sysid(session_dell, "20S6CTO1WW")) \
        == "ThinkPad T15 Type 20S6 20S7"


# ── Chaîne complète : ce qui finit réellement dans la commande DISM ────────

@pytest.fixture
def resolution(session_dell, monkeypatch):
    """Branche `_resolve_driver_dir` sur la base de test (elle ouvre sa propre session)."""
    monkeypatch.setattr(main, "engine", session_dell.get_bind())
    return session_dell


def _dir(**champs):
    from models import Machine
    return main._resolve_driver_dir(Machine(mac="aabbccddeeff", hostname="PC", **champs))


def test_un_pack_choisi_a_la_main_prime_sur_tout(resolution):
    pack = resolution.exec(
        select(DriverPack).where(DriverPack.model_key == "thinkpadt15type20s620s7")
    ).first()
    assert _dir(driver_pack_id=pack.id, hw_sysid="Dell Pro 14 Plus PB14250") \
        == "drivers\\lenovo\\t15"


def test_l_identifiant_materiel_cible_le_pack(resolution):
    assert _dir(hw_sysid="20S6CTO1WW") == "drivers\\lenovo\\t15"


def test_le_nom_commercial_dell_cible_le_pack(resolution):
    """La régression du 30/07 : sans pack manuel, on déversait tout le dossier."""
    assert _dir(hw_sysid="Dell Pro 14 Plus PB14250") == "drivers\\dell\\dellpro14pluspb14250"


def test_le_nom_du_firstboot_sert_de_dernier_recours(resolution):
    """`hw_model` n'est renseigné qu'au firstboot : absent du 1er déploiement."""
    assert _dir(hw_sysid="", hw_model="Dell Pro 14 Plus PB14250") \
        == "drivers\\dell\\dellpro14pluspb14250"


@pytest.mark.parametrize("champs", [
    {},                                                  # machine toute neuve
    {"hw_sysid": "Standard PC (Q35 + ICH9, 2009)"},       # VM QEMU
    {"hw_sysid": "Modele Jamais Vu 9000"},                # hors catalogue
])
def test_sans_correspondance_on_retombe_sur_le_dossier_complet(resolution, champs):
    """Repli sûr : lent, mais il ne manque jamais un pilote."""
    assert _dir(**champs) == "drivers"
