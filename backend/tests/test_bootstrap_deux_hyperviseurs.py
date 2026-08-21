# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Les agents d'amorçage ne s'adressaient qu'aux utilisateurs de Proxmox.

La dernière consigne affichée après le scellement disait « enchaîner sur
`qm template <vmid>` » — une commande qui n'existe pas sur vSphere. Or c'est
précisément le moment le plus délicat de la préparation : la VM vient de
s'éteindre, elle ne doit SURTOUT pas être rallumée, et l'opérateur cherche quoi
faire. Une consigne inapplicable à cet instant est pire qu'aucune consigne.

Constaté le 21/08 en préparant le premier gabarit Windows sur le vCenter.
"""
import pytest

from fastapi.testclient import TestClient


@pytest.fixture
def amorcage_windows(client):
    r = client.get("/bootstrap/windows")
    assert r.status_code == 200
    return r.text


@pytest.fixture
def amorcage_linux(client):
    r = client.get("/bootstrap/linux")
    assert r.status_code == 200
    return r.text


def test_lagent_windows_nomme_les_deux_hyperviseurs(amorcage_windows):
    assert "qm template" in amorcage_windows, "la voie Proxmox doit rester"
    assert "vSphere" in amorcage_windows, "la voie vSphere doit être nommée aussi"


def test_lagent_linux_nomme_les_deux_hyperviseurs(amorcage_linux):
    assert "qm template" in amorcage_linux
    assert "vSphere" in amorcage_linux


def test_lagent_windows_previent_de_ne_pas_rallumer(amorcage_windows):
    """Le seul avertissement qui coûte une préparation entière s'il manque : un
    unique démarrage consomme le passage OOBE, et le gabarit naît personnalisé."""
    assert "SANS rallumer" in amorcage_windows or "NE PAS la redemarrer" in amorcage_windows
