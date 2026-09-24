# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Profil, secrets masqués et configuration AD liée.

Trois défauts de la même famille — une valeur acceptée, sans l'effet annoncé :

- l'écran d'édition renvoie le profil tel qu'il l'a lu, secrets masqués en
  « *** » compris : enregistrer sans toucher au mot de passe remplaçait le
  mot de passe de jonction par trois étoiles (constaté le 24/09 sur un profil
  tout juste créé), et le suffixe TeamViewer de même ;
- `domain_config_id` et `laps_rotation_days` étaient absents du schéma de
  création, donc jetés sans un mot ;
- un profil lié à une configuration AD qui porte son propre compte gardait
  l'ancien compte du profil : ignoré au déploiement, mais affiché, stocké, et
  prêt à reprendre du service si l'on vidait le compte de la fiche.
"""
import main
from sqlmodel import Session

from crypto import decrypt, encrypt
from models import DomainConfig, Profile, engine


def _profil(**kw):
    with Session(engine) as s:
        p = Profile(name="P", os="windows", join_domain=True, **kw)
        s.add(p)
        s.commit()
        s.refresh(p)
        return p


def _config_ad(**kw):
    with Session(engine) as s:
        dc = DomainConfig(organization_id=1, name="Fiche", **kw)
        s.add(dc)
        s.commit()
        s.refresh(dc)
        return dc


def _relire(pid):
    with Session(engine) as s:
        return s.get(Profile, pid)


def test_la_creation_accepte_TOUS_les_champs_du_modele():
    absents = sorted(set(Profile.model_fields) - {"id"} - set(main.ProfileCreate.model_fields))
    assert not absents, f"champs du modèle absents de ProfileCreate : {absents}"


def test_renvoyer_le_profil_lu_ne_change_aucun_secret(client, admin_headers, clean_db):
    p = _profil(domain="exemple.test", domain_join_user="svc-join",
                domain_join_password=encrypt("vrai-mdp"), tv_suffix=encrypt("suffixe-tv"))
    lu = next(x for x in client.get("/profiles", headers=admin_headers).json() if x["id"] == p.id)
    assert lu["domain_join_password"] == "***" and lu["tv_suffix"] == "***"

    r = client.patch(f"/profiles/{p.id}", json=lu, headers=admin_headers)
    assert r.status_code == 200, r.text

    apres = _relire(p.id)
    assert decrypt(apres.domain_join_password) == "vrai-mdp"
    assert decrypt(apres.tv_suffix) == "suffixe-tv"


def test_mot_de_passe_vide_veut_dire_inchange(client, admin_headers, clean_db):
    p = _profil(domain_join_user="svc-join", domain_join_password=encrypt("vrai-mdp"))
    client.patch(f"/profiles/{p.id}", json={"domain_join_password": ""}, headers=admin_headers)
    assert decrypt(_relire(p.id).domain_join_password) == "vrai-mdp"


def test_vider_le_compte_efface_aussi_le_mot_de_passe(client, admin_headers, clean_db):
    p = _profil(domain_join_user="svc-join", domain_join_password=encrypt("vrai-mdp"))
    client.patch(f"/profiles/{p.id}", json={"domain_join_user": ""}, headers=admin_headers)
    apres = _relire(p.id)
    assert apres.domain_join_user == "" and apres.domain_join_password == ""


def test_creer_un_profil_lie_ne_garde_pas_de_compte_dormant(client, admin_headers, clean_db):
    dc = _config_ad(domain="client.local", join_user="svc-client", join_password=encrypt("x"))
    r = client.post("/profiles", headers=admin_headers, json={
        "name": "Lié", "os": "windows", "domain_config_id": dc.id, "laps_rotation_days": 30,
        "domain": "entreprise.local", "domain_join_user": "perso", "domain_join_password": "secret"})
    assert r.status_code == 201, r.text

    p = _relire(r.json()["id"])
    assert p.domain_config_id == dc.id
    assert p.laps_rotation_days == 30
    assert p.domain == "client.local"
    assert p.domain_join_user == "" and p.domain_join_password == ""


def test_lier_un_profil_existant_retire_son_compte(client, admin_headers, clean_db):
    dc = _config_ad(domain="client.local", join_user="svc-client", join_password=encrypt("x"))
    p = _profil(domain="client.local", domain_join_user="perso", domain_join_password=encrypt("y"))
    client.patch(f"/profiles/{p.id}", json={"domain_config_id": dc.id}, headers=admin_headers)
    apres = _relire(p.id)
    assert apres.domain_join_user == "" and apres.domain_join_password == ""
    with Session(engine) as s:
        assert main._resolve_domain(apres, s) == ("client.local", "svc-client", "x")


def test_une_fiche_sans_compte_laisse_celui_du_profil(client, admin_headers, clean_db):
    dc = _config_ad(domain="client.local", join_user="", join_password="")
    p = _profil(domain_join_user="svc-profil", domain_join_password=encrypt("y"))
    client.patch(f"/profiles/{p.id}", json={"domain_config_id": dc.id}, headers=admin_headers)
    apres = _relire(p.id)
    assert apres.domain_join_user == "svc-profil"
    assert decrypt(apres.domain_join_password) == "y"


def test_zero_detache_le_profil_de_sa_fiche(client, admin_headers, clean_db):
    dc = _config_ad(domain="client.local", join_user="svc-client", join_password=encrypt("x"))
    p = _profil(domain_config_id=dc.id)
    client.patch(f"/profiles/{p.id}", json={"domain_config_id": 0}, headers=admin_headers)
    assert _relire(p.id).domain_config_id is None


def test_une_fiche_inconnue_est_refusee(client, admin_headers, clean_db):
    p = _profil()
    r = client.patch(f"/profiles/{p.id}", json={"domain_config_id": 999}, headers=admin_headers)
    assert r.status_code == 400
    assert _relire(p.id).domain_config_id is None


def test_la_lecture_expose_TOUS_les_champs_du_modele(client, admin_headers, clean_db):
    """L'écran d'édition part de ce qu'il a lu : un champ absent de la lecture
    s'y affiche à sa valeur par défaut, quelle que soit la valeur enregistrée.
    La rotation LAPS apparaissait « désactivée » et la fiche AD liée, nulle part."""
    p = _profil()
    lu = next(x for x in client.get("/profiles", headers=admin_headers).json() if x["id"] == p.id)
    absents = sorted(set(Profile.model_fields) - set(lu))
    assert not absents, f"champs du modèle absents de la lecture d'un profil : {absents}"
