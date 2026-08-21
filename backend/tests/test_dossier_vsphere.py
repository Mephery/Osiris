# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""OSIRIS déversait toutes ses VM à la racine du datacenter.

Le vCenter de Namek est rangé par clients — `NAMEK`, `HC-DEV`, `Data-Expertise`,
`K8S`, `FRANCAS`, `TESSI`, `XIVO`… — et OSIRIS ignorait cette organisation sans
jamais poser la question. Signalé le 21/08 : une VM apparaissait juste sous le
dossier `XIVO` (la téléphonie), au point de sembler rangée dedans.

Le compromis retenu : accepter un nom court quand il ne désigne qu'un dossier,
exiger le chemin complet quand il est ambigu. Déposer la VM chez le mauvais
client est bien pire que refuser une saisie imprécise.
"""
import pytest
from fastapi import HTTPException

from vsphere import choisir_dossier

CHEMINS = [
    "NAMEK", "NAMEK/Prod", "NAMEK/Infra",
    "Data-Expertise", "Data-Expertise/Linux", "Data-Expertise/Linux/Infra",
    "XIVO", "TESSI", "No_Backup", "No_Backup/Templates",
]


# ── Ce qui est accepté ────────────────────────────────────────────────────────

def test_le_chemin_complet_est_accepte():
    assert choisir_dossier(CHEMINS, "Data-Expertise/Linux/Infra") == "Data-Expertise/Linux/Infra"


def test_un_nom_court_sans_ambiguite_suffit():
    """Exiger le chemin entier à chaque création serait pénible pour rien."""
    assert choisir_dossier(CHEMINS, "Templates") == "No_Backup/Templates"


def test_la_casse_est_indifferente():
    assert choisir_dossier(CHEMINS, "xivo") == "XIVO"


def test_les_barres_superflues_sont_tolerees():
    assert choisir_dossier(CHEMINS, "/NAMEK/Prod/") == "NAMEK/Prod"


def test_rien_de_demande_rend_la_racine():
    """Comportement d'origine conservé : ne rien saisir doit rester valide."""
    assert choisir_dossier(CHEMINS, "") == ""
    assert choisir_dossier(CHEMINS, "   ") == ""


# ── Ce qui est refusé ─────────────────────────────────────────────────────────

def test_un_nom_ambigu_est_REFUSE_et_liste_les_candidats():
    """`Infra` existe chez deux clients différents. Choisir au hasard déposerait
    la VM chez le mauvais — le refus est la bonne réponse, à condition de dire
    entre quoi trancher."""
    with pytest.raises(HTTPException) as exc:
        choisir_dossier(CHEMINS, "Infra")
    assert exc.value.status_code == 400
    assert "NAMEK/Infra" in exc.value.detail
    assert "Data-Expertise/Linux/Infra" in exc.value.detail


def test_un_dossier_inconnu_est_refuse():
    with pytest.raises(HTTPException) as exc:
        choisir_dossier(CHEMINS, "Comptabilite")
    assert exc.value.status_code == 400
    assert "introuvable" in exc.value.detail


def test_un_chemin_partiel_ne_passe_pas_pour_un_nom():
    """« Linux/Infra » n'est ni un chemin complet ni un nom de feuille : mieux
    vaut refuser que de deviner ce que l'opérateur avait en tête."""
    with pytest.raises(HTTPException):
        choisir_dossier(CHEMINS, "Linux/Infra")
