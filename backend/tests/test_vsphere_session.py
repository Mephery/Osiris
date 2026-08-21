# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Une session vCenter expirée était rendue comme si elle vivait encore.

Le contrôle de vivacité lisait `currentSession` sans jamais en regarder la
valeur. Or vCenter ne lève pas d'erreur sur une session expirée : il répond
`None`. Le contrôle passait donc, la session morte était rendue au demandeur, et
l'échec ne tombait que plus loin — en pleine création de VM, sous la forme d'un
500 nu « NotAuthenticated » que rien ne rattrapait, jusqu'à un redémarrage
manuel de l'API.

Constaté trois fois les 20 et 21/08, chaque fois en plein travail.
"""
import pytest

import vsphere


class _Session:
    """Une session vCenter, vue par le seul angle qui nous intéresse ici."""
    def __init__(self, courante):
        self.content = type("C", (), {
            "sessionManager": type("S", (), {"currentSession": courante})()
        })()


@pytest.fixture(autouse=True)
def _cache_propre():
    vsphere._sessions.clear()
    yield
    vsphere._sessions.clear()


class _Hyperviseur:
    id = 1
    token_id = "osiris@vsphere.local"
    token_secret = ""
    tls_verify = False
    url = "https://vcenter.test"
    name = "test"


def test_une_session_expiree_nest_pas_reutilisee(monkeypatch):
    """Le cœur du défaut : `currentSession` à None signifie expirée."""
    morte = _Session(courante=None)
    vsphere._sessions[1] = morte

    neuve = _Session(courante=object())
    monkeypatch.setattr(vsphere, "SmartConnect", lambda **kw: neuve)
    monkeypatch.setattr(vsphere, "decrypt", lambda _: "mot-de-passe")

    assert vsphere._connect(_Hyperviseur()) is neuve, \
        "une session dont currentSession est None doit être remplacée"


def test_une_session_vivante_est_reutilisee(monkeypatch):
    """Sans quoi on rouvrirait une session à chaque appel, et la création d'une VM
    en enchaîne une dizaine."""
    vivante = _Session(courante=object())
    vsphere._sessions[1] = vivante

    def _interdit(**kw):
        raise AssertionError("aucune reconnexion ne devait avoir lieu")
    monkeypatch.setattr(vsphere, "SmartConnect", _interdit)

    assert vsphere._connect(_Hyperviseur()) is vivante


def test_une_session_qui_leve_une_erreur_est_remplacee(monkeypatch):
    """L'autre forme d'expiration : certaines versions lèvent au lieu de rendre None."""
    class _Cassee:
        @property
        def content(self):
            raise RuntimeError("session invalide")

    vsphere._sessions[1] = _Cassee()
    neuve = _Session(courante=object())
    monkeypatch.setattr(vsphere, "SmartConnect", lambda **kw: neuve)
    monkeypatch.setattr(vsphere, "decrypt", lambda _: "mot-de-passe")

    assert vsphere._connect(_Hyperviseur()) is neuve
