# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""La liste des pilotes ne propose plus un Win10 quand le Win11 du même modèle
existe — sans perdre le repli Win10 des vieux modèles ni un pack déjà sur disque."""
from main import _sans_doublons_win10
from models import DriverPack


def _pack(id, os_code, status="available", model_key="elitebook8x5g8", vendor="hp"):
    return DriverPack(id=id, vendor=vendor, model=model_key, model_key=model_key,
                      os_code=os_code, download_url="", status=status)


def _ids(packs):
    return sorted(p.id for p in _sans_doublons_win10(packs))


def test_le_win10_d_un_modele_qui_a_un_win11_est_masque():
    assert _ids([_pack(1, "Windows11"), _pack(2, "Windows10")]) == [1]


def test_un_modele_sans_win11_garde_son_win10():
    assert _ids([_pack(1, "Windows10", model_key="vieuxmodele")]) == [1]


def test_un_win10_deja_sur_le_disque_ou_en_erreur_reste_visible():
    packs = [_pack(1, "Windows11"), _pack(2, "Windows10", "ready"),
             _pack(3, "Windows10", "error", model_key="autre"),
             _pack(4, "Windows11", model_key="autre")]
    assert _ids(packs) == [1, 2, 3, 4]


def test_le_meme_model_key_chez_un_autre_constructeur_ne_masque_rien():
    assert _ids([_pack(1, "Windows11", vendor="dell"), _pack(2, "Windows10")]) == [1, 2]
