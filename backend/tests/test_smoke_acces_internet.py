# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""La résolution DNS ne prouve pas que le trafic HTTPS sort du réseau.

Un pare-feu peut très bien laisser passer le DNS (port 53) et filtrer le port 443
plus strictement — un VLAN "sans internet" répondrait alors quand même au test de
résolution existant (`getent hosts www.google.com`), et une VM y serait déployée
sur la foi d'un test qui ne mesure pas ce qu'on lui demande. D'où un second test,
qui ouvre vraiment une connexion HTTPS sortante.
"""
import pytest


@pytest.fixture
def script(client, test_machine):
    """Le script de premier démarrage tel qu'OSIRIS le sert réellement."""
    resp = client.get(f"/firstboot-linux/{test_machine.mac}")
    assert resp.status_code == 200, resp.text
    return resp.text


def test_lacces_internet_est_teste_en_https_pas_seulement_en_dns(script):
    assert "curl -fsS -m 5 -o /dev/null https://www.google.com" in script, \
        "le test doit ouvrir une vraie connexion HTTPS, pas se contenter du DNS"


def test_lacces_internet_est_mesure_apres_la_resolution_dns(script):
    """Même famille de tests, même ordre de lecture : DNS avant HTTPS."""
    assert script.index('_add_test "Resolution DNS"') < script.index('_add_test "Acces internet')


def test_lechec_est_rapporte_avec_lurl_testee(script):
    """Le détail doit dire QUOI a été tenté, pas seulement que ça a échoué —
    sinon deux causes très différentes (DNS mort vs. port 443 filtré) se
    ressemblent dans le journal."""
    assert 'Acces internet (HTTPS)" false "https://www.google.com' in script


def test_le_succes_est_rapporte_sans_detail_superflu(script):
    assert '_add_test "Acces internet (HTTPS)" true' in script
