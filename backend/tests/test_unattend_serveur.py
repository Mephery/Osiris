# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Le mot de passe Administrateur des fichiers de réponses.

Windows Server en expérience utilisateur **exige** le mot de passe du compte
Administrateur intégré. Sans `<AdministratorPassword>`, l'OOBE s'arrête sur
« Personnaliser les paramètres » et attend une saisie qui ne viendra jamais.

Le symptôme est trompeur, parce que la machine a l'air vivante : la passe
`specialize` est déjà passée, donc elle porte son nom définitif, prend un bail
DHCP et répond même en WinRM. Mais `oobeSystem` ne se termine pas — aucun compte
local, aucune ouverture de session automatique, donc aucun `FirstLogonCommands`
et aucun premier démarrage OSIRIS. Constaté sur SRV-WIN-TPL le 2026-08-06 : le
port 5985 répondait et rejetait `osiris-admin`, qui n'avait jamais été créé.

Sans effet sur Windows 11, qui se passe très bien de cet élément.
"""
import xml.etree.ElementTree as ET

import re

import main
from crypto import decrypt
from models import Machine, engine
from sqlmodel import Session, select

MAC = "aabbccddeeff"
NS = {"u": "urn:schemas-microsoft-com:unattend"}


def _comptes(xml: str) -> ET.Element:
    racine = ET.fromstring(xml)
    for reglages in racine.findall("u:settings", NS):
        if reglages.get("pass") != "oobeSystem":
            continue
        for comp in reglages.findall("u:component", NS):
            comptes = comp.find("u:UserAccounts", NS)
            if comptes is not None:
                return comptes
    raise AssertionError("aucun UserAccounts dans la passe oobeSystem")


def test_lunattend_par_machine_fournit_le_mot_de_passe_administrateur(client, test_machine):
    comptes = _comptes(client.get(f"/unattend.xml?mac={MAC}").text)

    valeur = comptes.find("u:AdministratorPassword/u:Value", NS)
    assert valeur is not None, "sans lui, l'OOBE de Windows Server ne se termine jamais"
    # Propre à la machine et lisible dans OSIRIS : si LAPS échoue, c'est le seul
    # mot de passe administrateur local qu'elle aura.
    with Session(engine) as s:
        m = s.exec(select(Machine).where(Machine.mac == MAC)).one()
    assert valeur.text == decrypt(m.laps_password)


def test_lunattend_de_sysprep_fournit_le_mot_de_passe_administrateur(client):
    comptes = _comptes(client.get("/bootstrap/windows/unattend.xml").text)

    valeur = comptes.find("u:AdministratorPassword/u:Value", NS)
    assert valeur is not None
    assert len(valeur.text) >= 20


def test_lordre_des_elements_respecte_le_schema(client, test_machine):
    """
    L'ordre des enfants de UserAccounts est imposé par le schéma Microsoft
    (AdministratorPassword puis LocalAccounts). Un fichier hors séquence est
    rejeté en bloc, et Windows retombe sur un OOBE entièrement manuel.
    """
    for xml in (client.get(f"/unattend.xml?mac={MAC}").text,
                client.get("/bootstrap/windows/unattend.xml").text):
        enfants = [e.tag.split("}")[-1] for e in _comptes(xml)]
        assert enfants.index("AdministratorPassword") < enfants.index("LocalAccounts")


def test_aucun_mot_de_passe_nest_code_en_dur():
    """
    Il a vécu en clair dans le gabarit, puis en valeur par défaut dans main.py —
    donc publié avec le dépôt, et c'est lui qui servait en production faute de
    variable d'environnement. Plus aucune valeur fixe nulle part.
    """
    for fichier in ("main.py", "templates/unattend.xml.j2", "templates/unattend-sysprep.xml.j2"):
        with open(fichier, encoding="utf-8") as f:
            assert "OsirisAdmin" not in f.read(), fichier


def test_le_mot_de_passe_reste_le_meme_pendant_une_installation(client, test_machine):
    """WinPE peut relire le fichier de réponses : un mot de passe qui changerait
    entre deux lectures ne serait plus celui qu'OSIRIS a conservé."""
    lire = lambda: _comptes(client.get(f"/unattend.xml?mac={MAC}").text).find(
        "u:AdministratorPassword/u:Value", NS).text
    assert lire() == lire()


def test_deux_machines_n_ont_jamais_le_meme(client, test_machine):
    with Session(engine) as s:
        s.add(Machine(mac="aabbccddee00", hostname="PC-DEUX", client="c", os="windows"))
        s.commit()
    val = lambda mac: _comptes(client.get(f"/unattend.xml?mac={mac}").text).find(
        "u:AdministratorPassword/u:Value", NS).text
    assert val(MAC) != val("aabbccddee00")


def test_deux_gabarits_n_ont_jamais_le_meme(client):
    val = lambda: _comptes(client.get("/bootstrap/windows/unattend.xml").text).find(
        "u:AdministratorPassword/u:Value", NS).text
    assert val() != val()


def test_le_mot_de_passe_passe_la_complexite_windows():
    """Moins de trois classes de caractères : l'OOBE refuse le compte."""
    for _ in range(50):
        m = main._mot_de_passe_installation()
        assert re.search(r"[A-Z]", m) and re.search(r"[a-z]", m) and re.search(r"\d", m) \
            and re.search(r"[^A-Za-z0-9]", m)
