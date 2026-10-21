# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Capture d'image : WinPE écrit dans un dépôt, OSIRIS range dans le partage.

Le partage `windows` était ouvert en écriture à tout invité : n'importe qui sur
le réseau pouvait remplacer `curl.exe` ou `osiris-deploy.cmd`, que chaque PC
exécute en WinPE. Il passe en lecture seule ; seule la capture a besoin d'écrire,
elle le fait dans `captures`, et c'est OSIRIS qui déplace l'image à la fin.
"""
import pytest

import main

MAC = "aabbccddee10"


@pytest.fixture
def partages(tmp_path, monkeypatch):
    depot, partage = tmp_path / "captures", tmp_path / "windows"
    depot.mkdir()
    partage.mkdir()
    monkeypatch.setattr(main, "CAPTURE_SHARE_PATH", str(depot))
    monkeypatch.setattr(main, "WIN_SHARE_PATH", str(partage))
    main._capture_jobs.clear()
    yield depot, partage
    main._capture_jobs.clear()


def _enregistrer(client, admin_headers, nom="Golden_Image"):
    return client.post("/capture/register", params={"mac": MAC, "wim_name": nom}, headers=admin_headers)


def test_le_script_de_capture_ecrit_dans_le_depot_pas_dans_le_partage(client, admin_headers, partages):
    _enregistrer(client, admin_headers)
    script = main._build_capture_script(MAC).body.decode()
    assert "\\captures /user:guest" in script
    assert "\\windows /user:guest" not in script


def test_une_capture_reussie_est_rangee_dans_le_partage(client, admin_headers, partages):
    depot, partage = partages
    _enregistrer(client, admin_headers)
    main._build_capture_script(MAC)              # WinPE a reçu son script
    (depot / "Golden_Image.wim").write_bytes(b"wim")
    assert client.post(f"/capture/{MAC}/done", params={"success": True}).status_code == 200
    assert (partage / "Golden_Image.wim").read_bytes() == b"wim"
    assert not (depot / "Golden_Image.wim").exists()
    assert main._capture_jobs[MAC]["status"] == "done"


def test_un_succes_annonce_sans_fichier_est_un_echec_explique(client, admin_headers, partages):
    _enregistrer(client, admin_headers)
    main._build_capture_script(MAC)
    client.post(f"/capture/{MAC}/done", params={"success": True})
    job = main._capture_jobs[MAC]
    assert job["status"] == "failed" and "introuvable" in job["error"]


def test_rien_n_est_range_pour_une_capture_jamais_lancee(client, admin_headers, partages):
    """Route sans identifiant : elle ne doit pas pousser un fichier déposé par
    n'importe qui dans le dépôt tant qu'aucun script de capture n'a été servi."""
    depot, partage = partages
    _enregistrer(client, admin_headers)
    (depot / "Golden_Image.wim").write_bytes(b"pas une vraie capture")
    client.post(f"/capture/{MAC}/done", params={"success": True})
    assert not (partage / "Golden_Image.wim").exists()


@pytest.mark.parametrize("nom", ["install.wim", "INSTALL", "boot.wim"])
def test_une_capture_ne_peut_pas_ecraser_l_image_des_deploiements(client, admin_headers, partages, nom):
    r = _enregistrer(client, admin_headers, nom)
    assert r.status_code == 400
    assert MAC not in main._capture_jobs


@pytest.mark.parametrize("nom", ["..\\..\\x", "a b", "g&calc", "../x", "x\r\ny"])
def test_un_nom_qui_sortirait_du_dossier_ou_du_script_est_refuse(client, admin_headers, partages, nom):
    assert _enregistrer(client, admin_headers, nom).status_code == 400


def test_ranger_a_la_main_apres_une_capture_manuelle(client, admin_headers, partages):
    depot, partage = partages
    _enregistrer(client, admin_headers)
    main._capture_jobs[MAC]["status"] = "failed"
    (depot / "Golden_Image.wim").write_bytes(b"wim")
    r = client.post(f"/capture/{MAC}/ranger", headers=admin_headers)
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert (partage / "Golden_Image.wim").exists()


def test_ranger_est_reserve_aux_admins(client, partages):
    assert client.post(f"/capture/{MAC}/ranger").status_code in (401, 403)
