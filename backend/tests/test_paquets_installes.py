# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""OSIRIS annonçait « Installé : VLC » sur une machine où apt venait d'échouer.

Constaté le 2026-08-20 en déployant sur un VLAN de Namek sans route vers les
dépôts : le journal affichait fièrement « Installe : VLC » trois secondes après
« Installation des applications via apt... ». Le `_log` suivait l'appel à
`apt-get install` sans jamais regarder son code de retour.

Et rien ne rattrapait ce mensonge : le smoke test censé vérifier la présence des
paquets bouclait sur `ubuntu_packages`, une variable qu'aucun appelant n'a jamais
passée au gabarit. Le contrôle ne s'est donc **jamais** exécuté, sur aucune
machine, depuis qu'il existe. Les deux défauts se couvraient l'un l'autre : le
compte rendu mentait, et le seul garde-fou était mort-né.
"""
from pathlib import Path

import pytest

import main


class _App:
    """Une application Linux telle que le gabarit la consomme."""
    def __init__(self, name="VLC", apt_package="vlc"):
        self.name = name
        self.apt_package = apt_package
        self.linux_post_install = ""


def _script(apps):
    return main._firstboot_linux_content(
        hostname="srv-paquets", mac="aabbccddeeff", ou="",
        profile_ctx={"os": "ubuntu", "default_user": "humains", "join_domain": False,
                     "app_ids": "", "tv_suffix": "", "vm_data_disk_gb": 0},
        linux_apps=apps, zabbix=None, osiris_url="http://osiris.test",
    )


@pytest.fixture
def script():
    return _script([_App()])


def test_le_succes_nest_annonce_que_si_apt_a_reussi(script):
    """Le cœur du mensonge : `_log \"Installe\"` doit dépendre du code de retour."""
    bloc = script.split("Installation des applications via apt")[1].split("{% if zabbix")[0]

    assert "if apt-get install -y vlc" in bloc, \
        "l'installation doit être testée, pas lancée puis oubliée"
    position_log = bloc.index('_log "Installe : VLC"')
    position_if = bloc.index("if apt-get install")
    assert position_if < position_log, \
        "le compte rendu de succès doit être À L'INTÉRIEUR de la branche qui réussit"


def test_lechec_est_dit_et_nomme(script):
    """Un échec silencieux sur un site distant est indétectable : ni console, ni SSH."""
    assert "ECHEC : VLC" in script
    assert "vlc" in script.split("ECHEC : VLC")[1].split("\n")[0], \
        "le message doit nommer le paquet apt, pas seulement le libellé humain"


def test_lechec_ninterrompt_pas_le_deploiement(script):
    """Le reste de la configuration — supervision, /data, durcissement SSH — vaut
    d'être appliqué même si un paquet manque."""
    bloc = script.split("Installation des applications via apt")[1]
    assert "exit" not in bloc.split("{% if zabbix")[0].split("ECHEC : VLC")[1][:200], \
        "un paquet manquant ne doit pas arrêter le premier démarrage"


def test_la_presence_des_paquets_est_reellement_verifiee(script):
    """Le garde-fou mort-né : il bouclait sur une variable jamais fournie."""
    assert 'dpkg -s "vlc"' in script, \
        "la présence du paquet doit être vérifiée sur la machine"
    assert '_add_test "Paquet : VLC"' in script


def test_le_gabarit_ne_boucle_plus_sur_une_variable_fantome():
    """Contrôle sur la SOURCE du gabarit, pas sur le script rendu : c'est là que
    vivait le défaut. `ubuntu_packages` n'était passé par aucun appelant, donc le
    bloc entier était silencieusement sauté à chaque rendu."""
    gabarit = (Path(main.__file__).parent / "templates"
               / "firstboot-ubuntu.sh.j2").read_text(encoding="utf-8")

    assert "{% if ubuntu_packages %}" not in gabarit
    assert "{% for pkg in ubuntu_packages %}" not in gabarit


def test_le_controle_de_paquet_apparait_bien_dans_les_smoke_tests(script):
    """Il doit être rendu dans la section des smoke tests, pas ailleurs."""
    smoke = script.split("Smoke tests post-deploiement")[1]
    assert '_add_test "Paquet : VLC"' in smoke


def test_aucun_controle_de_paquet_quand_le_profil_nen_demande_aucun():
    """Un profil sans application ne doit pas produire de contrôle vide."""
    script = _script([])
    assert '_add_test "Paquet' not in script
