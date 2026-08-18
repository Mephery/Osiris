# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Le ping de la passerelle ne doit pas crier au loup quand l'ICMP est filtré.

Constaté le 2026-08-18 sur le premier déploiement complet d'un second site : sept
smoke tests, six au vert — dont « collecteur Zabbix joignable » — et un seul en
rouge, « passerelle inatteignable ». La passerelle était le pare-feu du site, qui
ne répond simplement pas à l'ICMP. La machine était parfaitement saine.

Une alarme permanente sur une machine saine coûte plus cher que le test ne
rapporte : au bout de deux fois, plus personne ne la lit — et le jour où elle dit
vrai, elle ne sera pas lue non plus. La sonde reste donc en place, mais elle ne
conclut à la panne que si rien d'autre ne prouve le routage.
"""
import pytest


@pytest.fixture
def script(client, test_machine):
    """Le script de premier démarrage tel qu'OSIRIS le sert réellement."""
    resp = client.get(f"/firstboot-linux/{test_machine.mac}")
    assert resp.status_code == 200, resp.text
    return resp.text


@pytest.fixture
def bloc(script):
    """La section qui juge la passerelle."""
    return script.split("# Ping passerelle par defaut")[1].split("_add_test \"Resolution DNS\"")[0]


def test_le_routage_est_mesure_avant_de_juger_la_passerelle(script):
    """Une résolution DNS qui aboutit sort du réseau : elle prouve le routage à elle
    seule. Encore faut-il la connaître AVANT de rendre le verdict."""
    avant = script.split("# Ping passerelle par defaut")[0]

    assert "_dns_ok=true" in avant, \
        "la résolution DNS doit être mesurée avant le verdict sur la passerelle"


def test_licmp_filtre_nest_pas_une_panne_si_le_routage_est_prouve(bloc):
    ok = bloc.split('elif [ "$_dns_ok" = "true" ]')[1].split("else")[0]

    assert " true " in ok, "ce cas doit être rapporté comme un succès"
    assert "ICMP" in ok, "le détail doit dire POURQUOI le ping n'a rien donné"


def test_une_passerelle_muette_sans_routage_reste_une_panne(bloc):
    """Le test garde toute sa valeur quand il n'y a rien d'autre pour trancher :
    c'est là qu'il localise la faute."""
    assert 'false "Passerelle inatteignable"' in bloc


def test_labsence_de_route_par_defaut_est_nommee_a_part(bloc):
    """Cause différente, correctif différent : ce n'est pas la passerelle qui se
    tait, c'est la VM qui n'en a aucune — un adressage incomplet, pas un filtre."""
    assert 'false "Aucune route par defaut"' in bloc


def test_lechec_dns_reste_rapporte(script):
    """Le nouvel enchaînement ne doit pas faire disparaître le test qui le porte."""
    assert 'Resolution DNS" false "Echec DNS"' in script
