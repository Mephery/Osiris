# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Schéma de partition du disque système LVM (disques.py).

Un seul disque : [EFI] + /boot + VG « osiris » { swap, /, extras… }. La fonction
sert l'aperçu du formulaire ET le dimensionnement du disque à provisionner, donc
on vérifie surtout la liste des tranches et la taille totale.
"""
import pytest
from fastapi import HTTPException

import disques
from disques import schema_partition, valider_systeme


def _par_montage(schema):
    return {t["montage"]: t for t in schema["tranches"]}


def test_schema_uefi_par_defaut():
    s = schema_partition()
    m = _par_montage(s)
    assert set(m) == {"/boot/efi", "/boot", "swap", "/"}
    assert m["/"]["taille_gb"] == disques.ROOT_GB_DEFAUT      # 200
    assert m["swap"]["taille_gb"] == disques.SWAP_GB_DEFAUT   # 2
    assert m["/boot"]["taille_gb"] == disques.BOOT_GB         # 1
    # EFI(0,5) + boot(1) + swap(2) + / (200) = 203,5 -> arrondi au Go supérieur
    assert s["total_gb"] == 204
    assert s["vg"] == "osiris"


def test_efi_et_boot_sont_des_partitions_le_reste_en_lvm():
    m = _par_montage(schema_partition())
    assert m["/boot/efi"]["type"] == "partition"
    assert m["/boot"]["type"] == "partition"
    assert m["swap"]["type"] == "lvm"
    assert m["/"]["type"] == "lvm"


def test_schema_bios_sans_efi():
    s = schema_partition(uefi=False)
    assert "/boot/efi" not in _par_montage(s)
    # boot(1) + swap(2) + / (200) = 203, pile
    assert s["total_gb"] == 203


def test_les_extras_sont_des_lv_et_comptent_dans_le_total():
    extras = [
        {"libelle": "home", "point_montage": "/home", "taille_gb": 50, "systeme_fichiers": "ext4"},
        {"libelle": "pg", "point_montage": "/var/lib/postgresql", "taille_gb": 80, "systeme_fichiers": "ext4"},
    ]
    s = schema_partition(root_gb=30, swap_gb=2, extras=extras)
    m = _par_montage(s)
    assert m["/home"]["type"] == "lvm" and m["/var/lib/postgresql"]["type"] == "lvm"
    # EFI(0,5)+boot(1)+swap(2)+/(30)+home(50)+pg(80) = 163,5 -> 164
    assert s["total_gb"] == 164


def test_taille_personnalisee():
    s = schema_partition(root_gb=100, swap_gb=4, uefi=False)
    m = _par_montage(s)
    assert m["/"]["taille_gb"] == 100 and m["swap"]["taille_gb"] == 4
    assert s["total_gb"] == 105   # 1 + 4 + 100


# ── Garde-fous ──────────────────────────────────────────────────────────────────

def test_root_trop_petit_refuse():
    with pytest.raises(HTTPException) as e:
        valider_systeme(root_gb=5, swap_gb=2)
    assert e.value.status_code == 422


def test_swap_hors_bornes_refuse():
    with pytest.raises(HTTPException):
        valider_systeme(root_gb=200, swap_gb=0)
    with pytest.raises(HTTPException):
        valider_systeme(root_gb=200, swap_gb=9999)


def test_systeme_valide_passe():
    valider_systeme(root_gb=200, swap_gb=2)   # ne lève pas


# ── Endpoint d'aperçu (formulaire) ──────────────────────────────────────────────

def test_endpoint_apercu(client, technician_headers):
    r = client.post("/vm/partition-preview",
                    json={"root_gb": 100, "swap_gb": 4, "uefi": False,
                          "disques": [{"taille_gb": 50, "point_montage": "/home", "libelle": "home"}]},
                    headers=technician_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total_gb"] == 1 + 4 + 100 + 50          # boot + swap + / + home
    assert {t["montage"] for t in data["tranches"]} == {"/boot", "swap", "/", "/home"}


def test_endpoint_apercu_refuse_root_trop_petit(client, technician_headers):
    r = client.post("/vm/partition-preview",
                    json={"root_gb": 5, "swap_gb": 2}, headers=technician_headers)
    assert r.status_code == 422


def test_endpoint_apercu_exige_auth(client):
    r = client.post("/vm/partition-preview", json={"root_gb": 200, "swap_gb": 2})
    assert r.status_code in (401, 403)
