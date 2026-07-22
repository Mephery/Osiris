# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Identification des machines par numéro de série (SMBIOS).

La MAC cesse d'identifier une machine dès qu'on déploie via un adaptateur
USB-Ethernet : le firmware peut présenter la MAC système ('MAC Address Pass
Through') pendant que WinPE présente la MAC gravée de l'adaptateur, et un même
adaptateur sert à plusieurs machines. Le numéro de série, lui, est stable.
"""
from sqlmodel import Session

from models import engine, Machine, OsImage, Profile


def _windows_image():
    with Session(engine) as s:
        s.add(OsImage(name="Win11", version="25H2", os="windows",
                      iso_url="file:///tmp/x.iso", status="ready"))
        s.commit()


def _machine(mac="aabbccddeeff", serial="SN-ABC-123", status="pending"):
    with Session(engine) as s:
        p = Profile(name="P-Win", os="windows", locale="fr-FR")
        s.add(p)
        s.commit()
        s.refresh(p)
        m = Machine(mac=mac, hostname="PC-SERIAL", client="Acme", os="windows",
                    hw_serial=serial, status=status, profile_id=p.id)
        s.add(m)
        s.commit()
    return mac


# ── /winpe-auto ───────────────────────────────────────────────────────────────

def test_winpe_auto_identifie_par_serial(client):
    """Le série résout la machine même si l'IP source n'est dans aucun bail DHCP."""
    _windows_image()
    _machine(serial="SN-ABC-123")

    r = client.get("/winpe-auto", params={"serial": "SN-ABC-123"})
    assert r.status_code == 200
    assert "PC-SERIAL" in r.text


def test_winpe_auto_serial_inconnu_refuse(client):
    """Un série inconnu ne doit surtout pas retomber sur un déploiement générique."""
    _windows_image()
    _machine(serial="SN-ABC-123")

    r = client.get("/winpe-auto", params={"serial": "SN-INCONNU"})
    assert r.status_code == 404
    assert "non identifiee" in r.text.lower()


def test_winpe_auto_serial_espaces_ignores(client):
    """wmic renvoie le série entouré d'espaces — ils ne doivent pas casser le lookup."""
    _windows_image()
    _machine(serial="SN-ABC-123")

    r = client.get("/winpe-auto", params={"serial": "  SN-ABC-123  "})
    assert r.status_code == 200
    assert "PC-SERIAL" in r.text


def test_winpe_auto_sans_serial_ni_bail_refuse(client):
    """Sans série et sans bail DHCP correspondant : refus explicite."""
    _windows_image()
    _machine()

    r = client.get("/winpe-auto")
    assert r.status_code == 404


# ── /boot : amorçage WinPE pour identification différée ───────────────────────

def test_boot_mac_inconnue_amorce_winpe_si_deploiement_en_attente(client):
    """MAC de l'adaptateur inconnue, mais une machine attend : on démarre WinPE
    pour qu'il s'identifie par son numéro de série."""
    _windows_image()
    _machine(mac="aabbccddeeff", serial="SN-ABC-123", status="pending")

    r = client.get("/boot", params={"mac": "00:e0:4c:68:06:36"})
    assert r.status_code == 200
    assert "wimboot" in r.text
    assert "boot.wim" in r.text
    # Sans la commande "boot" finale, iPXE télécharge tout puis ne démarre rien :
    # le poste rend la main au firmware ("no more network devices" + bip).
    assert r.text.rstrip().endswith("boot")


def test_boot_mac_inconnue_boot_local_si_rien_en_attente(client):
    """Aucun déploiement en attente : la machine inconnue rend la main au disque."""
    _windows_image()
    _machine(mac="aabbccddeeff", serial="SN-ABC-123", status="deployed")

    r = client.get("/boot", params={"mac": "00:e0:4c:68:06:36"})
    assert r.status_code == 200
    assert "wimboot" not in r.text
    assert "inconnue" in r.text.lower()


def test_boot_mac_inconnue_boot_local_si_pending_sans_serial(client):
    """Une machine en attente SANS série ne peut pas être identifiée dans WinPE :
    on ne démarre pas WinPE pour rien."""
    _windows_image()
    _machine(mac="aabbccddeeff", serial="", status="pending")

    r = client.get("/boot", params={"mac": "00:e0:4c:68:06:36"})
    assert r.status_code == 200
    assert "wimboot" not in r.text
