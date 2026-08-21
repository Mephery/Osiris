# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""La page « entrez votre clé de produit » arrêtait l'OOBE de tout clone Windows.

Constaté le 21/08 sur le premier gabarit du vCenter : le clone démarrait, le
sysprep se déroulait, VMware Tools tournait — et Windows attendait une saisie
humaine sur un écran bleu. Rien dans les journaux d'OSIRIS, pour une raison
simple : sans session ouverte, l'amorçage ne démarre pas, donc personne
n'appelle OSIRIS pour lui dire quoi que ce soit.

Pourquoi ça n'était jamais arrivé avant : les ISO utilisées jusque-là étaient
des versions d'ÉVALUATION, qui portent leur propre clé et sautent cet écran.
Le passage à un support sous licence — un progrès — a révélé le trou.

La correction ne consiste PAS à répondre à cette page mais à la supprimer : un
gabarit sert plusieurs clients, chacun avec sa licence, saisie après coup.
Graver une clé l'imposerait à tous les clones.
"""
import xml.etree.ElementTree as ET

import pytest

NS = {"u": "urn:schemas-microsoft-com:unattend"}
CLE = "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE"


def _xml(client, **params):
    r = client.get("/bootstrap/windows/unattend.xml", params=params)
    assert r.status_code == 200, r.text
    return ET.fromstring(r.text)


def _passe(racine, nom):
    for reglages in racine.findall("u:settings", NS):
        if reglages.get("pass") == nom:
            return reglages
    raise AssertionError(f"passe {nom} absente du fichier de réponses")


def _cle_gravee(racine):
    """La clé posée dans `specialize` — celle qui active Windows, s'il y en a une."""
    trouvees = [e.text for e in _passe(racine, "specialize").iter(f"{{{NS['u']}}}ProductKey")]
    return trouvees[0] if trouvees else None


# ── La leçon du 21/08 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("params", [{}, {"product_key": CLE}])
def test_aucun_UserData_dans_la_passe_oobeSystem(client, params):
    """Tentative ratée, gardée comme garde-fou.

    Pour éviter d'imposer une licence à tous les clones, `UserData/ProductKey`
    avec `WillShowUI = Never` avait été posé dans `oobeSystem` pour masquer la
    page de saisie. Cet élément n'y est PAS valide, et Windows ne pardonne pas :
    il rejette la passe ENTIÈRE, pas seulement l'élément fautif. Conséquence sur
    la VM de test : plus de session automatique, donc plus d'amorçage, donc plus
    aucun rappel — et une boîte de dialogue en console pour tout diagnostic.

    Il n'existe aucune directive pour masquer cette page. La réponse est une
    GVLK, clé publique de Microsoft qui n'active ni ne consomme rien.
    """
    oobe = _passe(_xml(client, **params), "oobeSystem")
    assert not list(oobe.iter(f"{{{NS['u']}}}UserData"))


# ── Sans clé ──────────────────────────────────────────────────────────────────

def test_sans_cle_aucune_cle_n_est_gravee(client):
    """Sinon on imposerait la licence d'un client à tous les autres."""
    assert _cle_gravee(_xml(client)) is None


# ── Avec clé : le cas du client qui a sa propre licence de volume ─────────────

def test_avec_cle_elle_est_gravee_dans_specialize(client):
    assert _cle_gravee(_xml(client, product_key=CLE)) == CLE


def test_une_cle_minuscule_est_normalisee(client):
    assert _cle_gravee(_xml(client, product_key=CLE.lower())) == CLE


# ── Refus ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mauvaise", [
    "pas-une-cle",
    "AAAAA-BBBBB-CCCCC-DDDDD",           # quatre groupes
    "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE-FFF", # cinq et demi
    "AAAA-BBBBB-CCCCC-DDDDD-EEEEE",      # premier groupe trop court
])
def test_une_cle_mal_formee_est_refusee(client, mauvaise):
    """Une clé fantaisiste ne produirait aucune erreur ici : elle ferait échouer
    la passe `specialize` en silence, sur chaque clone, des semaines plus tard."""
    r = client.get("/bootstrap/windows/unattend.xml", params={"product_key": mauvaise})
    assert r.status_code == 400


def test_pas_d_injection_dans_le_fichier_de_reponses(client):
    """Ce paramètre finit dans un XML gravé pour tous les clones d'un gabarit."""
    r = client.get("/bootstrap/windows/unattend.xml",
                   params={"product_key": "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE</ProductKey><X/>"})
    assert r.status_code == 400


# ── Le rendu reste exploitable ────────────────────────────────────────────────

@pytest.mark.parametrize("params", [{}, {"product_key": CLE}])
def test_le_fichier_reste_un_xml_bien_forme(client, params):
    """Un fichier de réponses mal formé est ignoré par sysprep SANS message."""
    racine = _xml(client, **params)
    assert racine.tag.endswith("unattend")
    for passe in ("specialize", "oobeSystem"):
        _passe(racine, passe)


def test_l_amorcage_reste_declenche_dans_les_deux_cas(client):
    """Non-régression : quoi qu'on fasse de la clé, la session automatique et sa
    première commande — l'amorçage OSIRIS — doivent survivre."""
    for params in ({}, {"product_key": CLE}):
        r = client.get("/bootstrap/windows/unattend.xml", params=params)
        assert "osiris-bootstrap.ps1" in r.text
        assert "<Enabled>true</Enabled>" in r.text
