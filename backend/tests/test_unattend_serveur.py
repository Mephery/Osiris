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

import main
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
    assert valeur.text == main.WINDOWS_TEMPLATE_ADMIN_PASSWORD


def test_lunattend_de_sysprep_fournit_le_mot_de_passe_administrateur(client):
    comptes = _comptes(client.get("/bootstrap/windows/unattend.xml").text)

    valeur = comptes.find("u:AdministratorPassword/u:Value", NS)
    assert valeur is not None
    assert valeur.text == main.WINDOWS_TEMPLATE_ADMIN_PASSWORD


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


def test_aucun_mot_de_passe_nest_code_en_dur_dans_le_gabarit():
    """
    Il vivait en clair à trois endroits du gabarit. Le rassembler sur une constante
    permet d'en changer sans en oublier un — et de le faire depuis l'environnement.
    """
    gabarit = (main.jinja_env.get_template("unattend.xml.j2")
               .filename)
    with open(gabarit, encoding="utf-8") as f:
        contenu = f.read()
    assert main.WINDOWS_TEMPLATE_ADMIN_PASSWORD not in contenu
