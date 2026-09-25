# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""La distribution d'un gabarit, pour proposer d'abord ceux du système choisi.

Choisir Ubuntu et voir un gabarit Debian proposé à égalité obligeait à savoir
lequel prendre. Rien ne déclare la distribution partout : le type d'invité
vSphere la porte, Proxmox non — il ne reste alors que le nom du gabarit.
"""
import pytest

import main


@pytest.mark.parametrize("modele, attendu", [
    ({"name": "gabarit-a", "famille": "linux", "guest_id": "ubuntu64Guest"}, "ubuntu"),
    ({"name": "gabarit-b", "famille": "linux", "guest_id": "debian11_64Guest"}, "debian"),
    ({"name": "ubuntu-24.04-osiris-v3", "famille": "linux"}, "ubuntu"),
    ({"name": "template-Debian12-v1", "famille": "linux"}, "debian"),
    ({"name": "srv-tpl", "famille": "windows", "guest_id": "windows9Server64Guest"}, "windows"),
])
def test_la_distribution_est_reconnue(modele, attendu):
    assert main._distribution_gabarit(modele) == attendu


def test_le_type_d_invite_prime_sur_le_nom():
    """Le type d'invité est déclaré à l'hyperviseur ; le nom, écrit à la main."""
    assert main._distribution_gabarit(
        {"name": "ubuntu-ancien", "famille": "linux", "guest_id": "debian10_64Guest"}) == "debian"


def test_ne_rien_trouver_ne_devine_rien():
    """Un gabarit sans indice reste proposé sans être classé : mieux vaut ne pas
    trier que cacher à tort."""
    assert main._distribution_gabarit({"name": "linux-generique", "famille": "linux"}) == ""
    assert main._distribution_gabarit(
        {"name": "rocky", "famille": "linux", "guest_id": "otherLinux64Guest"}) == ""


def test_un_mot_qui_contient_le_nom_ne_suffit_pas():
    """« xubuntu » n'est pas « ubuntu » : le nom doit commencer un mot."""
    assert main._distribution_gabarit({"name": "xubuntu-poste", "famille": "linux"}) == ""
