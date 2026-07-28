# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Tests de la livraison des pilotes réseau WinPE par wimboot (main.py).

Contexte : WinPE ne dispose que des pilotes *inbox* de l'ISO. Sur une machine
dont la carte réseau n'est pas reconnue (ThinkPad T15…), il n'y a aucun réseau
et le déploiement est bloqué net. Les pilotes ont d'abord été bakés dans
boot.wim, mais le WIM ainsi produit ne démarrait plus sous wimboot. Ils sont
désormais passés à wimboot en `initrd` supplémentaires : il les dépose dans
`\\Windows\\System32\\` sans toucher au WIM.
"""
import os

import pytest

import main


@pytest.fixture
def drivers_dir(tmp_path, monkeypatch):
    """Redirige WINPE_DRIVERS_PATH vers un dossier de test."""
    monkeypatch.setattr(main, "WINPE_DRIVERS_PATH", str(tmp_path))
    return tmp_path


def _driver(root, sub, *names):
    d = root / sub
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / n).write_text("x")


def test_chaque_fichier_pilote_donne_une_ligne_initrd(drivers_dir):
    _driver(drivers_dir, "net/N2YRW10W", "e1d.inf", "e1d.sys", "e1d.cat")
    out = main._winpe_driver_initrd_lines()

    assert out.count("initrd --name") == 3
    for name in ("e1d.inf", "e1d.sys", "e1d.cat"):
        assert f"initrd --name {name} " in out


def test_les_fichiers_sont_aplatis_dans_system32(drivers_dir):
    """System32 est un espace de noms plat : wimboot doit recevoir le nom seul
    comme destination, sinon le .inf et son .sys ne se retrouvent pas côte à
    côte et drvload échoue."""
    _driver(drivers_dir, "net/N2YRW10W", "e1d.inf")
    line = main._winpe_driver_initrd_lines().strip()

    # forme attendue : initrd --name <nom> <url arborescente> <nom>
    assert line.startswith("initrd --name e1d.inf ")
    assert line.endswith(" e1d.inf")
    assert "/static/winpe-drivers/net/N2YRW10W/e1d.inf" in line


def test_noms_en_collision_une_seule_ligne(drivers_dir):
    """Deux pilotes homonymes s'écraseraient en silence dans System32."""
    _driver(drivers_dir, "net/A", "pilote.inf")
    _driver(drivers_dir, "net/B", "pilote.inf")
    out = main._winpe_driver_initrd_lines()

    assert out.count("initrd --name") == 1


def test_dossier_absent_ne_produit_aucune_ligne(monkeypatch):
    monkeypatch.setattr(main, "WINPE_DRIVERS_PATH", "/nexiste/pas")
    assert main._winpe_driver_initrd_lines() == ""


def test_dossier_vide_ne_produit_aucune_ligne(drivers_dir):
    assert main._winpe_driver_initrd_lines() == ""


def test_les_espaces_du_chemin_sont_encodes(drivers_dir):
    _driver(drivers_dir, "net/Intel I219", "e1d.inf")
    out = main._winpe_driver_initrd_lines()

    assert "Intel%20I219" in out
    assert "Intel I219" not in out


# ── Chaîne de démarrage complète ───────────────────────────────────────────

def test_la_chaine_garde_les_quatre_fichiers_wimboot(drivers_dir):
    """Les pilotes s'ajoutent à la chaîne, ils ne la remplacent pas."""
    _driver(drivers_dir, "net/N2YRW10W", "e1d.inf")
    chain = main._winpe_chain_lines()

    assert "/static/wimboot" in chain
    for f in ("bootmgr", "BCD", "boot.sdi", "boot.wim"):
        assert f"initrd --name {f} " in chain
    assert "initrd --name e1d.inf " in chain


def test_boot_wim_reste_avant_les_pilotes(drivers_dir):
    """wimboot identifie l'image par son extension .wim, mais on garde l'ordre
    historique (les 4 fichiers d'abord) pour ne rien changer au démarrage."""
    _driver(drivers_dir, "net/N2YRW10W", "e1d.inf")
    chain = main._winpe_chain_lines()

    assert chain.index("boot.wim") < chain.index("e1d.inf")
