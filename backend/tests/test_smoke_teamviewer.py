# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Le smoke test TeamViewer ne s'exécute pas sur un serveur.

TeamViewer est un outil d'accès distant de POSTE. Sur un serveur, il n'est pas
installé — mais le smoke test le cherchait quand même, et affichait un
« [FAIL] TeamViewer : Service introuvable » trompeur à chaque déploiement serveur
alors que tout allait bien. Vu sur les clones Windows Server le 2026-08-06.
"""
from jinja2 import Environment, FileSystemLoader


def _rendre(machine_type: str) -> str:
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    return env.get_template("firstboot-windows.ps1.j2").render(
        machine=type("M", (), {"hostname": "X", "mac": "aabbccddeeff", "ou": ""})(),
        profile={
            "locale": "fr-FR", "keyboard": "fr", "timezone": "Europe/Paris",
            "join_domain": False, "domain": "", "domain_join_user": "",
            "domain_join_password": "", "enable_bitlocker": False,
            "bitlocker_pin": False, "laps_rotation_days": 0, "network_drives": "",
            "printers": "", "post_script": "", "wifi_ssid": "", "wifi_password": "",
            "default_user": "osiris", "machine_type": machine_type,
        },
        tv_password="", win_apps=[], osiris_url="http://osiris", osiris_ip="10.0.0.1",
        bios_password="", forced_mac="",
    )


def test_un_serveur_ne_teste_pas_teamviewer():
    assert 'Add-SmokeTest "TeamViewer"' not in _rendre("server")


def test_un_poste_teste_toujours_teamviewer():
    assert 'Add-SmokeTest "TeamViewer"' in _rendre("workstation")
