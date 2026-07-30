# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Réglages matériel imposés par le client : mot de passe BIOS et convention MAC.

Certains clients imposent un plan d'adressage : les postes s'appellent `<PREFIXE>nnn`
et doivent porter une MAC `<4 octets>:XX:YY` où `XXYY` reprend les 3 derniers chiffres
du hostname, zéro-padés sur 4 et RECOPIÉS TELS QUELS — pas convertis en hexa. C'est le
piège de ce calcul : le poste 100 donne `01:00`, et non `00:64` comme le ferait une
conversion décimale.

Valeurs d'exemple ici : préfixe hostname `PC`, préfixe MAC `02aabbcc`.
"""
import pytest
from fastapi import HTTPException

import main
from main import _validate_mac_prefix, mac_from_hostname

PREFIXE = "02aabbcc"


# ── Dérivation de la MAC depuis le hostname ────────────────────────────────

@pytest.mark.parametrize("hostname,attendu", [
    ("PC095", "02aabbcc0095"),
    ("PC098", "02aabbcc0098"),
    ("PC099", "02aabbcc0099"),
    ("PC100", "02aabbcc0100"),   # PAS 0064 : recopie, pas de conversion decimale
    ("PC000", "02aabbcc0000"),   # borne basse
    ("PC999", "02aabbcc0999"),   # borne haute : tient encore sur 2 octets
    ("pc095", "02aabbcc0095"),   # la casse du prefixe n'entre pas dans le calcul
])
def test_mac_derivee_du_hostname(hostname, attendu):
    assert mac_from_hostname(hostname, PREFIXE) == attendu


def test_la_correspondance_est_bijective_de_000_a_999():
    """Aucune collision : deux postes distincts ne peuvent pas partager une MAC."""
    macs = {mac_from_hostname(f"PC{n:03d}", PREFIXE) for n in range(1000)}
    assert len(macs) == 1000


@pytest.mark.parametrize("hostname", [
    "SRV-TEST",      # aucun chiffre
    "PC9",           # moins de 3 chiffres
    "PC12",
    "",
])
def test_hostname_hors_convention_ne_produit_pas_de_mac(hostname):
    """Plutot que d'inventer une MAC, on s'abstient : le template saute l'etape."""
    assert mac_from_hostname(hostname, PREFIXE) == ""


def test_sans_prefixe_la_fonctionnalite_est_inactive():
    assert mac_from_hostname("PC095", "") == ""


# ── Validation du préfixe saisi en UI ──────────────────────────────────────

@pytest.mark.parametrize("brut,attendu", [
    ("02aabbcc",            "02aabbcc"),
    ("02:AA:BB:CC",         "02aabbcc"),   # separateurs et casse normalises
    ("02-aa-bb-cc",         "02aabbcc"),
    ("  02AABBCC  ",        "02aabbcc"),
    ("",                    ""),           # vide = desactive
    (None,                  ""),
])
def test_prefixe_normalise(brut, attendu):
    assert _validate_mac_prefix(brut) == attendu


@pytest.mark.parametrize("brut", [
    "02aabb",        # trop court
    "02aabbccdd",    # trop long
    "02aabbzz",      # pas de l'hexa
])
def test_prefixe_malforme_refuse(brut):
    with pytest.raises(HTTPException) as exc:
        _validate_mac_prefix(brut)
    assert exc.value.status_code == 400


def test_prefixe_multicast_refuse():
    """Bit multicast a 1 => adresse source invalide, la machine perdrait le reseau."""
    with pytest.raises(HTTPException) as exc:
        _validate_mac_prefix("03aabbcc")
    assert "multicast" in exc.value.detail


# ── Rendu du template firstboot ────────────────────────────────────────────

def _render(**extra):
    ctx = {
        "machine": type("M", (), {"hostname": "PC099", "mac": "02aabbcc0099"})(),
        "profile": {"machine_type": "workstation", "join_domain": False,
                    "enable_bitlocker": False, "network_drives": [], "printers": [],
                    "post_script": "", "wifi_ssid": "", "laps_rotation_days": 0},
        "tv_password": "", "win_apps": [],
        "osiris_url": "http://osiris", "osiris_ip": "10.0.0.1",
        "bios_password": "", "forced_mac": "",
    }
    ctx.update(extra)
    return main.jinja_env.get_template("firstboot-windows.ps1.j2").render(**ctx)


def test_sans_reglages_aucune_des_deux_sections_n_est_rendue():
    script = _render()
    assert "DellBIOSProvider" not in script
    assert "Set-NetAdapter" not in script


def test_le_mot_de_passe_bios_est_injecte_et_le_module_charge():
    script = _render(bios_password="S3cr3t!")
    assert "DellBIOSProvider" in script
    assert "'S3cr3t!'" in script
    assert "DellSmbios:\\Security\\AdminPassword" in script


def test_apostrophe_du_mot_de_passe_echappee():
    """Une apostrophe non doublee terminerait la chaine PowerShell et casserait le script."""
    script = _render(bios_password="aujourd'hui")
    assert "'aujourd''hui'" in script


def test_la_mac_imposee_est_injectee():
    script = _render(forced_mac="02aabbcc0099")
    assert "Set-NetAdapter" in script
    assert "$targetMac = '02aabbcc0099'" in script


def test_la_mac_est_appliquee_apres_les_smoke_tests():
    """Set-NetAdapter redemarre l'interface : tout ce qui a besoin du reseau passe avant."""
    script = _render(forced_mac="02aabbcc0099")
    assert script.index("smoke-tests") < script.index("Set-NetAdapter")
