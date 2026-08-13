# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""L'ISO WinPE ne se régénère pas quand boot.wim change.

C'est un geste manuel, donc un geste oublié. Et l'oubli ne produit aucune erreur :
les VM démarrent, se déploient et rapportent un succès — avec l'ancien WinPE.
Ces tests vérifient qu'OSIRIS refuse ce scénario au lieu de le laisser passer.
"""
import os

import pytest

import main


@pytest.fixture
def iso_et_wim(tmp_path, monkeypatch):
    """Détourne les deux chemins vers des fichiers jetables."""
    iso = tmp_path / "osiris-winpe.iso"
    wim = tmp_path / "boot.wim"
    monkeypatch.setattr(main, "WINPE_ISO_PATH", str(iso))
    monkeypatch.setattr(main, "WINPE_BOOT_WIM_PATH", str(wim))
    return iso, wim


def _dater(chemin, horodatage):
    chemin.write_bytes(b"x")
    os.utime(chemin, (horodatage, horodatage))


def test_iso_absente(iso_et_wim):
    _, wim = iso_et_wim
    _dater(wim, 1_000_000)
    assert main.etat_iso_winpe() == "absente"


def test_iso_plus_ancienne_que_boot_wim(iso_et_wim):
    iso, wim = iso_et_wim
    _dater(iso, 1_000_000)
    _dater(wim, 2_000_000)          # boot.wim reconstruit après l'ISO
    assert main.etat_iso_winpe() == "perimee"


def test_iso_plus_recente_que_boot_wim(iso_et_wim):
    iso, wim = iso_et_wim
    _dater(wim, 1_000_000)
    _dater(iso, 2_000_000)
    assert main.etat_iso_winpe() == "ok"


def test_boot_wim_absent_ne_declenche_pas_de_fausse_alerte(iso_et_wim):
    """Une installation sans boot.wim local n'est pas une installation périmée."""
    iso, _ = iso_et_wim
    _dater(iso, 1_000_000)
    assert main.etat_iso_winpe() == "ok"


def test_health_expose_l_etat(client, iso_et_wim):
    iso, wim = iso_et_wim
    _dater(iso, 1_000_000)
    _dater(wim, 2_000_000)
    body = client.get("/health").json()
    assert body["winpe"] == "perimee"
    # Une ISO périmée n'est pas une indisponibilité : le service répond, et une
    # sonde doit pouvoir distinguer les deux situations.
    assert body["status"] == "ok"
