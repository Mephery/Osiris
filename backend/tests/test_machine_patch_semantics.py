# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Tests de la sémantique du PATCH machine (lost update / vidage de champ).

Le 2026-07-16, un `driver_pack_id` corrigé côté serveur est revenu à son
ancienne valeur : la modale d'édition renvoyait le formulaire ENTIER, donc les
valeurs lues à son ouverture, périmées depuis. Le correctif est en deux temps —
l'UI n'envoie plus que les champs modifiés, et le serveur ne considère plus que
les champs réellement présents dans la requête (exclude_unset).

Effet de bord corrigé au passage : un `null` explicite vide désormais le champ,
là où il était ignoré. Retirer le pack de pilotes d'une machine n'avait aucun
effet et échouait en silence.
"""


def _machine(client, admin_headers, **extra):
    payload = {"mac": "aa:bb:cc:00:11:22", "client": "Acme", "os": "windows",
               "hostname": "PC-TEST", "ou": "", **extra}
    r = client.post("/machines", json=payload, headers=admin_headers)
    assert r.status_code == 201, r.text
    return payload["mac"]


# ── Champs absents : jamais touchés ────────────────────────────────────────

def test_un_champ_absent_de_la_requete_est_preserve(client, admin_headers):
    """Le cœur du lost update : ce que la requête ne mentionne pas ne bouge pas."""
    mac = _machine(client, admin_headers, hostname="PC-ORIGINE")

    r = client.patch(f"/machines/{mac}", json={"client": "NouveauClient"},
                     headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["hostname"] == "PC-ORIGINE"
    assert r.json()["client"] == "NouveauClient"


def test_patch_vide_ne_change_rien(client, admin_headers):
    mac = _machine(client, admin_headers, hostname="PC-ORIGINE")

    r = client.patch(f"/machines/{mac}", json={}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["hostname"] == "PC-ORIGINE"


# ── null explicite : vide le champ quand il est nullable ───────────────────

def test_null_explicite_retire_le_pack_de_pilotes(client, admin_headers):
    """Avant, ce null était ignoré : le pack restait collé à la machine."""
    mac = _machine(client, admin_headers)
    client.patch(f"/machines/{mac}", json={"profile_id": None}, headers=admin_headers)

    r = client.patch(f"/machines/{mac}", json={"driver_pack_id": None},
                     headers=admin_headers)
    assert r.status_code == 200

    detail = client.get(f"/machines/{mac}", headers=admin_headers).json()
    assert detail.get("driver_pack_id") in (None, 0, "")


def test_null_sur_un_champ_texte_est_ignore(client, admin_headers):
    """hostname est NOT NULL en base : un null doit être ignoré, pas planter."""
    mac = _machine(client, admin_headers, hostname="PC-ORIGINE")

    r = client.patch(f"/machines/{mac}", json={"hostname": None}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["hostname"] == "PC-ORIGINE"


# ── Scénario complet du 2026-07-16 ─────────────────────────────────────────

def test_une_fiche_perimee_n_ecrase_plus_une_correction_serveur(client, admin_headers):
    """Reproduction : la fiche est ouverte, le serveur corrige un champ, puis la
    fiche est enregistrée sans que ce champ ait été touché."""
    mac = _machine(client, admin_headers, hostname="PC-ORIGINE")

    # La fiche est ouverte — l'UI mémorise cet état.
    ouverte = client.get(f"/machines/{mac}", headers=admin_headers).json()

    # Entre-temps, le champ est corrigé côté serveur.
    client.patch(f"/machines/{mac}", json={"client": "ClientCorrige"},
                 headers=admin_headers)

    # L'utilisateur ne modifie que le hostname : l'UI n'envoie que celui-là.
    modifie = {**ouverte, "hostname": "PC-RENOMME"}
    diff = {k: v for k, v in modifie.items()
            if k in ("hostname", "client", "ou") and v != ouverte.get(k)}
    assert diff == {"hostname": "PC-RENOMME"}

    r = client.patch(f"/machines/{mac}", json=diff, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["hostname"] == "PC-RENOMME"
    assert r.json()["client"] == "ClientCorrige"   # la correction a survécu
