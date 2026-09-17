# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Il n'y avait AUCUNE contrainte sur les mots de passe.

`password: str`, sans le moindre contrôle : un compte pouvait naître avec « a ».
Sur un outil qui détient les clés BitLocker, les mots de passe LAPS, les comptes
de jonction AD et les jetons d'hyperviseurs, c'est le maillon qui décide de tout
le reste.

La règle est bâtie sur la LONGUEUR, pas sur des classes de caractères imposées :
exiger « une majuscule, un chiffre, un symbole » produit massivement des
`P@ssw0rd1`, satisfaisant la contrainte pour une entropie dérisoire. Ces tests
verrouillent ce choix autant que les seuils.
"""
import pytest
from fastapi import HTTPException

from auth import LONGUEUR_MINIMALE, valider_force_mot_de_passe


def _refus(mdp, email=""):
    with pytest.raises(HTTPException) as e:
        valider_force_mot_de_passe(mdp, email)
    assert e.value.status_code == 400
    return e.value.detail


# ── Longueur ──────────────────────────────────────────────────────────────────

def test_trop_court_est_refuse():
    detail = _refus("Abc1!" * 2)            # 10 caractères
    assert str(LONGUEUR_MINIMALE) in detail, "le refus doit dire le seuil attendu"


def test_le_seuil_est_atteignable():
    valider_force_mot_de_passe("correct cheval batterie agrafe")


def test_une_phrase_sans_aucun_symbole_passe():
    """Le coeur du choix : la longueur, pas la ponctuation décorative."""
    valider_force_mot_de_passe("quatre mots choisis au hasard")


def test_un_p_arobase_ssw0rd_court_ne_passe_PAS():
    """Toutes les classes de caractères, et pourtant le premier essayé."""
    _refus("P@ssw0rd1")


# ── La troncature bcrypt, piège silencieux ────────────────────────────────────

def test_au_dela_de_72_octets_c_est_refuse():
    """bcrypt IGNORE le reste : deux mots de passe partageant leurs 72 premiers
    octets ouvriraient le même compte, et une phrase longue choisie pour être
    forte serait tronquée sans que rien ne le dise."""
    detail = _refus("a1B2c3D4e5" * 8)       # 80 caractères
    assert "72" in detail


def test_exactement_72_octets_passe():
    # Assez varié pour ne pas tomber sur la règle de répétition : on teste ICI
    # la borne haute, pas la diversité.
    mdp = "phrase de passe longue mais parfaitement valable quand meme abcdefgh"
    assert len(mdp.encode("utf-8")) == 68
    valider_force_mot_de_passe(mdp + "1234")   # exactement 72 octets


def test_la_limite_se_compte_en_OCTETS_pas_en_CARACTERES():
    """Un accent pèse deux octets, un emoji quatre : compter les caractères
    laisserait passer une valeur que bcrypt tronquerait quand même."""
    _refus("é" * 40)                        # 40 caractères, 80 octets


# ── Ce que la seule longueur laisse passer ────────────────────────────────────

def test_repetition_refusee():
    detail = _refus("a" * 20)
    assert "repetitif" in detail.lower() or "répétitif" in detail.lower()


def test_motif_court_repete_refuse():
    _refus("123123123123123")


def test_mot_de_passe_courant_refuse():
    _refus("passwordpassword")


# ── Ce que l'attaquant sait déjà ──────────────────────────────────────────────

def test_le_nom_du_compte_dans_le_mot_de_passe_est_refuse():
    detail = _refus("coline-un-mot-de-passe-long", "coline@exemple.fr")
    assert "coline" in detail


def test_le_nom_de_l_outil_est_refuse():
    _refus("osiris-mot-de-passe-tres-long")


def test_un_local_part_trop_court_ne_declenche_pas_de_faux_refus():
    """Un compte « a@… » ferait sinon refuser tout mot de passe contenant un
    « a » — soit à peu près tous."""
    valider_force_mot_de_passe("une phrase parfaitement valable", "a@exemple.fr")


# ── Chaque refus doit se laisser corriger ─────────────────────────────────────

@pytest.mark.parametrize("mdp,email", [
    ("court", ""),
    ("a" * 20, ""),
    ("passwordpassword", ""),
    ("aB3" * 30, ""),
    ("coline-mot-de-passe-long", "coline@exemple.fr"),
])
def test_chaque_refus_DIT_sa_cause(mdp, email):
    """« Mot de passe trop faible » oblige à deviner, et l'utilisateur retente en
    boucle des variantes qui échouent pour la même raison invisible."""
    detail = _refus(mdp, email)
    assert len(detail) > 40, detail
    assert detail.rstrip().endswith((".", "!")), detail
