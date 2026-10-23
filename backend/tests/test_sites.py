# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Sites distants : le cache rend compte de sa copie de nuit, OSIRIS dit s'il est à jour.

Le risque visé : un cache en retard d'une image installe l'ancienne version sur
les PC de son site, journal au vert. L'onglet Sites doit le dire, et un faux
compte rendu ne doit pas pouvoir le masquer.
"""
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import main
import sites
from models import Site


@pytest.fixture
def partage(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "WIN_SHARE_PATH", str(tmp_path))
    return tmp_path


def _image(dossier, nom, taille=10, mtime=1_700_000_000):
    chemin = dossier / nom
    chemin.write_bytes(b"x" * taille)
    os.utime(chemin, (mtime, mtime))
    return {"nom": nom, "taille": taille, "mtime": mtime}


def _creer(client, admin_headers, nom="Paris"):
    r = client.post("/sites", json={"nom": nom}, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()


def _rapport(client, jeton, **corps):
    corps.setdefault("ok", True)
    return client.post("/sites/rapport", json=corps, headers={main.ENTETE_JETON_SITE: jeton})


def _etat(client, admin_headers, nom="Paris"):
    return next(s for s in client.get("/sites", headers=admin_headers).json() if s["nom"] == nom)["etat"]


# ── Ce qu'OSIRIS attend du cache ──────────────────────────────────────────────

def test_seules_les_images_servies_sont_attendues(partage):
    attendue = _image(partage, "install.wim")
    _image(partage, "boot.wim.bak-20260716")
    _image(partage, "boot.wim.ko-20260722")
    (partage / "curl.exe").write_bytes(b"x")
    assert sites.images_presentes(str(partage)) == [attendue]


def test_les_exclusions_sont_les_memes_des_deux_cotes():
    """Le cache ne reçoit pas ce que rsync exclut ; s'il fallait le lui réclamer,
    il serait déclaré en écart pour toujours."""
    conf = (Path(__file__).parents[2] / "deploy/cache/rsyncd-cache.conf.example").read_text()
    ligne = re.search(r"^exclude = (.*)$", conf, re.M).group(1).split()
    assert sorted(ligne) == sorted(sites.EXCLUSIONS)


# ── Création et jeton ─────────────────────────────────────────────────────────

def test_le_jeton_est_montre_une_fois_et_seule_son_empreinte_est_gardee(client, admin_headers, partage):
    cree = _creer(client, admin_headers)
    assert cree["jeton"]
    assert "jeton" not in client.get("/sites", headers=admin_headers).json()[0]
    with main.Session(main.engine) as s:
        site = s.get(Site, cree["id"])
        assert site.jeton_empreinte and cree["jeton"] not in site.jeton_empreinte


def test_un_site_neuf_n_a_jamais_rendu_compte(client, admin_headers, partage):
    _creer(client, admin_headers)
    assert _etat(client, admin_headers)["code"] == "jamais"


def test_deux_sites_ne_portent_pas_le_meme_nom(client, admin_headers, partage):
    _creer(client, admin_headers)
    assert client.post("/sites", json={"nom": "Paris"}, headers=admin_headers).status_code == 400


def test_creer_un_site_est_reserve_aux_admins(client, technician_headers, partage):
    assert client.post("/sites", json={"nom": "Paris"}, headers=technician_headers).status_code == 403


# ── Compte rendu du cache ─────────────────────────────────────────────────────

def test_sans_jeton_ou_avec_un_faux_le_compte_rendu_est_refuse(client, admin_headers, partage):
    _creer(client, admin_headers)
    assert client.post("/sites/rapport", json={"ok": True}).status_code == 401
    assert _rapport(client, "pas-le-bon").status_code == 403
    assert _etat(client, admin_headers)["code"] == "jamais"


def test_un_ancien_jeton_ne_vaut_plus_apres_renouvellement(client, admin_headers, partage):
    cree = _creer(client, admin_headers)
    nouveau = client.post(f"/sites/{cree['id']}/jeton", headers=admin_headers).json()["jeton"]
    assert _rapport(client, cree["jeton"]).status_code == 403
    assert _rapport(client, nouveau).status_code == 200


def test_cache_avec_les_memes_images_est_a_jour(client, admin_headers, partage):
    image = _image(partage, "install.wim")
    jeton = _creer(client, admin_headers)["jeton"]
    assert _rapport(client, jeton, images=[image]).json()["etat"] == "a_jour"
    etat = _etat(client, admin_headers)
    assert etat["code"] == "a_jour" and etat["ecarts"] == []


def test_image_absente_alors_que_la_copie_a_reussi_est_signalee(client, admin_headers, partage):
    _image(partage, "install.wim", mtime=1_600_000_000)
    jeton = _creer(client, admin_headers)["jeton"]
    _rapport(client, jeton, images=[])
    etat = _etat(client, admin_headers)
    assert etat["code"] == "images_differentes"
    assert etat["ecarts"] == [{"nom": "install.wim", "probleme": "absente du cache", "attendue_cette_nuit": False}]


def test_image_modifiee_apres_la_copie_est_attendue_cette_nuit_pas_une_panne(client, admin_headers, partage):
    """Une image refaite à 14 h n'est pas sur le cache avant la nuit : c'est normal,
    et l'opérateur ne doit pas chercher une panne."""
    ancienne = _image(partage, "install.wim", mtime=1_600_000_000)
    jeton = _creer(client, admin_headers)["jeton"]
    _rapport(client, jeton, images=[ancienne])
    plus_tard = int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp())
    _image(partage, "install.wim", taille=20, mtime=plus_tard)
    etat = _etat(client, admin_headers)
    assert etat["code"] == "a_jour"
    assert etat["ecarts"][0]["attendue_cette_nuit"] is True
    assert "cette nuit" in etat["message"]


def test_une_copie_ratee_garde_la_liste_de_la_derniere_reussite(client, admin_headers, partage):
    image = _image(partage, "install.wim")
    jeton = _creer(client, admin_headers)["jeton"]
    _rapport(client, jeton, images=[image])
    _rapport(client, jeton, ok=False, erreur="rsync windows : code 12", images=[])
    etat = _etat(client, admin_headers)
    assert etat["code"] == "echec"
    assert "rsync windows : code 12" in etat["message"]
    assert etat["ecarts"] == []


def test_la_reussite_suivante_efface_l_erreur(client, admin_headers, partage):
    jeton = _creer(client, admin_headers)["jeton"]
    _rapport(client, jeton, ok=False, erreur="fenetre terminee")
    _rapport(client, jeton)
    assert _etat(client, admin_headers)["code"] == "a_jour"


def test_sans_copie_reussie_depuis_deux_nuits_le_site_est_en_retard(partage):
    site = Site(nom="Paris", rapport_le=datetime.now(timezone.utc),
                copie_reussie_le=datetime.now(timezone.utc) - timedelta(hours=50))
    etat = sites.etat(site, [])
    assert etat["code"] == "en_retard"
    assert "50 h" in etat["message"]
