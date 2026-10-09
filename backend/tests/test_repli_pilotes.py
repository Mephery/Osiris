# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Un poste physique sans pack de pilotes prêt pour son modèle.

Avant : repli « tout le dossier ». DISM poussait les 40 Go du partage (2 276 .inf
en octobre 2026) : 65 paquets en 45 min au banc le 08/10, soit ~26 h estimées,
WinPE apparemment figé — pour installer surtout les pilotes d'AUTRES modèles.

Maintenant (choix du 09/10) : rien n'est injecté, Windows démarre sur ses
pilotes intégrés et Windows Update complète ; le journal dit pourquoi. Et si le
catalogue connaît le pack du modèle sans qu'il soit téléchargé — cas courant :
une dizaine de packs téléchargés sur près de deux mille —, OSIRIS le télécharge
en tâche de fond pour le prochain poste de ce modèle.
"""
import re

import pytest
from sqlmodel import Session, select

import main
from models import DriverPack, Machine, OsImage, engine

MAC = "aabbccddeeff"


@pytest.fixture(autouse=True)
def demandes_oubliees():
    main._packs_demandes.clear()
    yield
    main._packs_demandes.clear()


@pytest.fixture
def pret(test_machine):
    with Session(engine) as session:
        session.add(OsImage(name="Windows 11", os="windows", version="24H2",
                            status="ready", iso_url="", wim_name="install.wim"))
        session.commit()


def _sysid(valeur: str):
    with Session(engine) as session:
        m = session.exec(select(Machine).where(Machine.mac == MAC)).first()
        m.hw_sysid = valeur
        session.add(m)
        session.commit()


def _pack_au_catalogue(status="available") -> int:
    with Session(engine) as session:
        p = DriverPack(vendor="dell", model="Latitude 7450", model_key="latitude7450",
                       os_code="Windows11", download_url="http://x/7450", status=status)
        session.add(p)
        session.commit()
        return p.id


def _script(client) -> str:
    return client.get(f"/winpe-script/{MAC}").text


# ── Le script WinPE ───────────────────────────────────────────────────────────

def test_sans_pack_le_script_n_injecte_rien_et_dit_pourquoi(client, pret):
    _sysid("Modele Jamais Vu 9000")
    script = _script(client)
    assert "/Add-Driver" not in script
    assert "aucun+pack+au+catalogue+pour+Modele+Jamais+Vu+9000" in script


def test_un_pack_au_catalogue_est_telecharge_pour_la_suite(client, pret, monkeypatch):
    pack_id = _pack_au_catalogue()
    _sysid("Latitude 7450")
    lances = []
    monkeypatch.setattr(main, "_telecharger_pour_la_suite",
                        lambda p: lances.append(p.id) or True)
    script = _script(client)
    assert lances == [pack_id]
    assert "/Add-Driver" not in script, "ce poste-ci part sans : le pack n'est pas là"
    assert "en+cours+de+telechargement+pour+le+prochain+deploiement" in script


def test_si_le_telechargement_ne_part_pas_le_journal_dit_quoi_faire(client, pret, monkeypatch):
    _pack_au_catalogue()
    _sysid("Latitude 7450")
    monkeypatch.setattr(main, "_telecharger_pour_la_suite", lambda p: False)
    assert "a+telecharger+depuis+l+onglet+Pilotes" in _script(client)


def test_un_nom_de_modele_ne_peut_pas_injecter_de_commande(client, pret):
    """Le message est écrit tel quel dans un .cmd : « & » y enchaînerait une
    AUTRE commande, « % » serait développé."""
    _sysid("Acme & calc.exe (100%) ^ | >")
    script = _script(client)
    # Seule la partie qui vient du nom du modèle est vérifiée : le reste de la
    # ligne (redirection « 2>&1 », variables %MAC%) est écrit par OSIRIS.
    morceaux = re.findall(r"msg=Aucun\+pack[^\"]*", script) \
        + re.findall(r"Aucun pack de pilotes pret : (.*)", script)
    assert len(morceaux) == 2
    for m in morceaux:
        assert "Acme" in m and "calc.exe" in m
        assert not any(c in m for c in "&()^|<>%"), m


def test_une_vm_ne_cherche_rien_au_catalogue(client, pret, monkeypatch):
    _pack_au_catalogue()
    _sysid("Latitude 7450")
    with Session(engine) as session:
        m = session.exec(select(Machine).where(Machine.mac == MAC)).first()
        m.proxmox_vm_id, m.proxmox_node = 123, "pve"
        session.add(m)
        session.commit()
    lances = []
    monkeypatch.setattr(main, "_telecharger_pour_la_suite", lambda p: lances.append(p) or True)
    script = _script(client)
    assert lances == []
    assert "pilotes+constructeurs+inutiles" in script


# ── Le lancement du téléchargement ────────────────────────────────────────────

class _FileArq:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, nom, *args):
        self.jobs.append((nom, *args))


@pytest.fixture
def file_arq(monkeypatch):
    f = _FileArq()
    monkeypatch.setattr(main, "arq_pool", f)
    # Hors d'un thread de FastAPI, pas de portail vers la boucle : on exécute
    # la coroutine directement.
    import asyncio
    monkeypatch.setattr(main.anyio.from_thread, "run",
                        lambda fn, *a: asyncio.run(fn(*a)))
    return f


def _pack(status) -> DriverPack:
    return DriverPack(id=42, vendor="dell", model="X", model_key="x", os_code="Windows11",
                      download_url="http://x", status=status)


def test_le_telechargement_est_lance_une_seule_fois(file_arq):
    assert main._telecharger_pour_la_suite(_pack("available")) is True
    assert main._telecharger_pour_la_suite(_pack("available")) is True
    assert file_arq.jobs == [("download_driver_pack", 42)]


def test_un_pack_en_erreur_est_retente(file_arq):
    assert main._telecharger_pour_la_suite(_pack("error")) is True
    assert file_arq.jobs == [("download_driver_pack", 42)]


def test_un_pack_deja_en_cours_n_est_pas_relance(file_arq):
    assert main._telecharger_pour_la_suite(_pack("downloading")) is True
    assert file_arq.jobs == []


def test_sans_file_arq_rien_ne_casse(monkeypatch):
    monkeypatch.setattr(main, "arq_pool", None)
    assert main._telecharger_pour_la_suite(_pack("available")) is False


def test_une_file_en_panne_ne_fait_pas_echouer_le_deploiement(monkeypatch):
    monkeypatch.setattr(main, "arq_pool", _FileArq())

    def panne(*a):
        raise ConnectionError("redis injoignable")
    monkeypatch.setattr(main.anyio.from_thread, "run", panne)
    assert main._telecharger_pour_la_suite(_pack("available")) is False
