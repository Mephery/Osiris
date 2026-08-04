# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Reprise de la jonction au domaine sur panne réseau.

Le 2026-08-04 sur M2KL099, le tunnel VPN vers le client était tombé au moment précis
de la jonction — qui se joue quelques secondes après le démarrage du firstboot. Un
essai unique, donc une jonction à refaire à la main. La reprise couvre ce cas.

Le point délicat n'est PAS de réessayer, mais de savoir quand ne pas le faire : le
compte de jonction est un compte de service, et cinq essais avec un mauvais mot de
passe le feraient verrouiller par la stratégie AD.
"""
import re

import pytest
from jinja2 import Environment, FileSystemLoader

# Le motif qui décide « on réessaie » / « on s'arrête », tel qu'écrit dans le template.
MOTIF_IDENTIFIANTS = (
    r"0x52e|\b1326\b|mot de passe|password|informations d.identification|credential"
)

# Message RÉEL relevé dans le journal de M2KL099 le 2026-08-04.
PANNE_RESEAU_REELLE = (
    "L'ordinateur « M2KL099 » n'a pas pu joindre le domaine « midi2i.com » a partir "
    "de son groupe de travail actuel « WORKGROUP » avec le message d'erreur suivant : "
    "Le domaine specifie n'existe pas ou n'a pas pu etre contacte."
)


def _est_erreur_identifiants(message: str) -> bool:
    """Reproduit le `-match` du template (même syntaxe de regex qu'en PowerShell)."""
    return bool(re.search(MOTIF_IDENTIFIANTS, message))


# ── Distinction panne réseau / identifiants refusés ────────────────────────

@pytest.mark.parametrize("message", [
    PANNE_RESEAU_REELLE,
    "Le domaine specifie n'existe pas ou n'a pas pu etre contacte.",
    "The specified domain either does not exist or could not be contacted.",
    # Piège : un hostname qui contient le code d'erreur des identifiants.
    "L'ordinateur « M2KL1326 » n'a pas pu joindre le domaine : injoignable.",
])
def test_une_panne_reseau_est_rejouee(message):
    assert not _est_erreur_identifiants(message)


@pytest.mark.parametrize("message", [
    "Le nom d'utilisateur ou le mot de passe est incorrect",
    "The user name or password is incorrect",
    "Access is denied. (Exception from HRESULT: 0x52e)",
    "Echec de connexion : erreur 1326",
])
def test_des_identifiants_refuses_arretent_tout(message):
    """Insister verrouillerait le compte de service côté AD."""
    assert _est_erreur_identifiants(message)


# ── Rendu du template ──────────────────────────────────────────────────────

@pytest.fixture
def firstboot():
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    return env.get_template("firstboot-windows.ps1.j2").render(
        machine=type("M", (), {"hostname": "PC-TEST", "mac": "aabbccddeeff", "ou": ""})(),
        profile={
            "locale": "fr-FR", "keyboard": "fr", "timezone": "Europe/Paris",
            "join_domain": True, "domain": "exemple.local",
            "domain_join_user": "svc_join", "domain_join_password": "secret",
            "enable_bitlocker": False, "bitlocker_pin": False, "laps_rotation_days": 0,
            "network_drives": "", "printers": "", "post_script": "",
            "wifi_ssid": "", "wifi_password": "", "default_user": "osiris",
        },
        tv_password="", win_apps=[], osiris_url="http://osiris", osiris_ip="10.0.0.1",
        bios_password="", forced_mac="",
    )


def test_la_boucle_de_reprise_est_bien_rendue(firstboot):
    assert "$djMaxEssais = 5" in firstboot
    assert "Start-Sleep -Seconds $djAttente" in firstboot
    assert "for ($djEssai = 1; $djEssai -le $djMaxEssais; $djEssai++)" in firstboot


def test_le_motif_du_template_est_celui_qu_on_teste(firstboot):
    """Garde-fou : si le template change, les tests ci-dessus doivent suivre."""
    assert MOTIF_IDENTIFIANTS in firstboot


def test_les_accolades_du_script_sont_equilibrees(firstboot):
    """Aucun PowerShell sur l'hôte de build : à défaut d'un vrai parseur, on vérifie
    au moins que la boucle ajoutée ne déséquilibre pas le script."""
    sans_chaines = re.sub(r"'[^'\n]*'|\"[^\"\n]*\"", "", firstboot)
    assert sans_chaines.count("{") == sans_chaines.count("}")
    assert sans_chaines.count("(") == sans_chaines.count(")")


def test_un_profil_sans_jonction_ne_rend_aucune_reprise():
    env = Environment(loader=FileSystemLoader("templates"), trim_blocks=True,
                      lstrip_blocks=True, autoescape=False)
    out = env.get_template("firstboot-windows.ps1.j2").render(
        machine=type("M", (), {"hostname": "PC-TEST", "mac": "aabbccddeeff", "ou": ""})(),
        profile={
            "locale": "fr-FR", "keyboard": "fr", "timezone": "Europe/Paris",
            "join_domain": False, "domain": "", "domain_join_user": "",
            "domain_join_password": "", "enable_bitlocker": False,
            "bitlocker_pin": False, "laps_rotation_days": 0, "network_drives": "",
            "printers": "", "post_script": "", "wifi_ssid": "", "wifi_password": "",
            "default_user": "osiris",
        },
        tv_password="", win_apps=[], osiris_url="http://osiris", osiris_ip="10.0.0.1",
        bios_password="", forced_mac="",
    )
    assert "djMaxEssais" not in out
