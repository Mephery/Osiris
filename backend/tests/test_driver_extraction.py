# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Tests unitaires de l'extraction des packs de pilotes (worker.py).

Contexte : les packs Lenovo sont livrés en installeurs Inno Setup, que 7-Zip ne
sait pas ouvrir — il n'en sort que les ressources du binaire Windows. Le pack
1321 (ThinkPad T15g) a ainsi occupé 1,6 Go sur le partage sans contenir un seul
pilote. D'où la détection de format, l'aplatissement des pseudo-racines Inno et
le refus d'un pack sans .inf.
"""
import os

import pytest

from worker import _count_inf, _flatten_inno_output, _is_inno_setup, _move_merge


# ── Détection de format ────────────────────────────────────────────────────

def test_is_inno_setup_reconnait_un_installeur_inno(tmp_path):
    exe = tmp_path / "pack.exe"
    exe.write_bytes(b"MZ" + b"\x00" * 2048 + b"Inno Setup Setup Data (5.5.7) (u)" + b"\x00" * 512)
    assert _is_inno_setup(str(exe)) is True


def test_is_inno_setup_rejette_une_archive_ordinaire(tmp_path):
    cab = tmp_path / "pack.cab"
    cab.write_bytes(b"MSCF" + b"\x00" * 4096)
    assert _is_inno_setup(str(cab)) is False


def test_is_inno_setup_ne_lit_que_l_entete(tmp_path):
    """La signature au-delà de l'en-tête ne doit pas être prise pour un Inno :
    on ne veut pas qu'une chaîne apparaissant dans un pilote fasse basculer
    l'extraction vers innoextract."""
    exe = tmp_path / "gros.bin"
    exe.write_bytes(b"\x00" * (512 * 1024 + 16) + b"Inno Setup")
    assert _is_inno_setup(str(exe)) is False


# ── Aplatissement des pseudo-racines Inno ──────────────────────────────────

def _touch(path: str, content: str = "x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


@pytest.mark.parametrize("pseudo", ["code$GetExtractPath$", "app", "tmp"])
def test_flatten_remonte_le_contenu_des_pseudo_racines(tmp_path, pseudo):
    staging, dest = tmp_path / "s", tmp_path / "d"
    _touch(str(staging / pseudo / "Chipset" / "c.inf"))
    _flatten_inno_output(str(staging), str(dest))

    assert (dest / "Chipset" / "c.inf").exists()
    assert not (dest / pseudo).exists()


def test_flatten_conserve_les_dossiers_ordinaires(tmp_path):
    staging, dest = tmp_path / "s", tmp_path / "d"
    _touch(str(staging / "Ethernet" / "e.inf"))
    _touch(str(staging / "README.txt"))
    _flatten_inno_output(str(staging), str(dest))

    assert (dest / "Ethernet" / "e.inf").exists()
    assert (dest / "README.txt").exists()


def test_flatten_fusionne_deux_pseudo_racines_qui_se_recouvrent(tmp_path):
    """shutil.move() seul imbriquerait le second Audio dans le premier
    (dest/Audio/Audio) au lieu de réunir leurs contenus."""
    staging, dest = tmp_path / "s", tmp_path / "d"
    _touch(str(staging / "code$A$" / "Audio" / "x" / "a.inf"))
    _touch(str(staging / "app" / "Audio" / "y" / "b.inf"))
    _flatten_inno_output(str(staging), str(dest))

    assert (dest / "Audio" / "x" / "a.inf").exists()
    assert (dest / "Audio" / "y" / "b.inf").exists()
    assert not (dest / "Audio" / "Audio").exists()


def test_move_merge_ecrase_un_fichier_en_conflit(tmp_path):
    src, dst = tmp_path / "src.txt", tmp_path / "dst.txt"
    src.write_text("neuf")
    dst.write_text("vieux")
    _move_merge(str(src), str(dst))

    assert dst.read_text() == "neuf"
    assert not src.exists()


# ── Comptage des .inf (garde-fou anti-pack-vide) ───────────────────────────

def test_count_inf_parcourt_toute_l_arborescence(tmp_path):
    _touch(str(tmp_path / "Audio" / "a.inf"))
    _touch(str(tmp_path / "Chipset" / "sub" / "b.INF"))   # casse indifférente
    _touch(str(tmp_path / "Chipset" / "c.sys"))
    assert _count_inf(str(tmp_path)) == 2


def test_count_inf_vaut_zero_sur_une_extraction_ratee(tmp_path):
    """Forme exacte des déchets laissés par 7z sur le pack 1321 : les
    ressources du binaire PE, et pas un seul pilote."""
    _touch(str(tmp_path / "[0]"))
    _touch(str(tmp_path / "CERTIFICATE"))
    assert _count_inf(str(tmp_path)) == 0
