# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Dupliquer un profil en perdait DOUZE champs.

La duplication recopiait les champs un à un. Chaque champ ajouté ensuite au
modèle — clé SSH, type de machine, serveurs NTP, miroir apt, gabarit matériel
des VM — n'y a jamais été ajouté, alors que le docstring annonçait « tous les
champs sauf l'id ».

Le plus coûteux était `ssh_authorized_keys` : dupliquer un profil qui marche
donnait un profil déployant des machines où PERSONNE ne peut entrer, sans le
moindre avertissement. Constaté le 17/09, juste après s'être fait enfermer
dehors par un profil sans clé.

Le test porte sur l'invariant — « tout champ du modèle est copié » — et non sur
une liste figée : c'est l'énumération qui avait dérivé, en recopier une ici
reproduirait exactement le défaut.
"""
import pytest
from sqlmodel import Session, select

from models import Profile, engine


@pytest.fixture
def profil_rempli(clean_db):
    """Un profil dont AUCUN champ n'est laissé à sa valeur par défaut.

    Sans ça, un champ oublié par la duplication passerait inaperçu : sa valeur
    par défaut et sa valeur copiée se ressembleraient.
    """
    with Session(engine) as s:
        p = Profile(
            name="Source", os="ubuntu", locale="en_US.UTF-8", keyboard="us",
            timezone="Europe/Lisbon", default_user="marcel", extra_packages="htop,vim",
            join_domain=False, domain="exemple.test", domain_join_user="svc-join",
            win_image="image.wim", win_index=3, enable_bitlocker=False,
            bitlocker_pin=True, network_drives='[{"letter":"Z"}]',
            printers='["\\\\\\\\srv\\\\imp"]', post_script="echo bonjour",
            tv_suffix="", app_ids="1,2", laps_rotation_days=42,
            machine_type="server", ssh_authorized_keys="ssh-ed25519 AAAAquelquechose",
            ntp_servers="10.0.0.1", apt_mirror="http://miroir.test",
            apt_proxy="http://proxy.test:3142", set_root_password=True,
            vm_vcpus=8, vm_ram_mb=16384, vm_disk_gb=200, vm_data_disk_gb=500,
        )
        s.add(p)
        s.commit()
        s.refresh(p)
        return p


def test_la_duplication_copie_TOUS_les_champs(client, admin_headers, profil_rempli):
    r = client.post(f"/profiles/{profil_rempli.id}/clone", headers=admin_headers)
    assert r.status_code == 201, r.text

    with Session(engine) as s:
        copie = s.get(Profile, r.json()["id"])

    ignores = {"id", "name"}          # l'id est neuf, le nom est suffixé exprès
    perdus = [c for c in Profile.model_fields
              if c not in ignores
              and getattr(copie, c) != getattr(profil_rempli, c)]
    assert not perdus, f"champs perdus à la duplication : {perdus}"


def test_la_cle_SSH_survit_a_la_duplication(client, admin_headers, profil_rempli):
    """Le champ qui coûtait le plus cher : sans lui, le profil dupliqué déploie
    des machines inaccessibles — et rien ne le dit."""
    r = client.post(f"/profiles/{profil_rempli.id}/clone", headers=admin_headers)
    with Session(engine) as s:
        copie = s.get(Profile, r.json()["id"])
    assert copie.ssh_authorized_keys == profil_rempli.ssh_authorized_keys


def test_la_copie_est_un_NOUVEAU_profil(client, admin_headers, profil_rempli):
    r = client.post(f"/profiles/{profil_rempli.id}/clone", headers=admin_headers)
    assert r.json()["id"] != profil_rempli.id
    assert r.json()["name"] != profil_rempli.name
    with Session(engine) as s:
        assert len(s.exec(select(Profile)).all()) == 2


def test_dupliquer_un_profil_inexistant_rend_404(client, admin_headers, clean_db):
    assert client.post("/profiles/999999/clone", headers=admin_headers).status_code == 404


# ── Ce qu'on peut modifier après coup ─────────────────────────────────────────
# Pydantic IGNORE en silence un champ qu'il ne connaît pas. Un champ absent de
# `ProfilePatch` se laisse donc modifier dans l'interface, part dans la requête,
# et disparaît sans le moindre message — l'utilisateur voit sa saisie, croit
# l'avoir enregistrée, et rien n'a changé.

def test_TOUT_champ_du_modele_est_modifiable(client, admin_headers):
    """L'invariant, pas une liste : c'est une énumération figée qui avait dérivé.

    `laps_rotation_days` était affiché ET modifiable dans le formulaire, et
    jamais enregistré. `os` ne l'était pas non plus, ce qui enfermait toute
    copie de profil dans l'OS de sa source.
    """
    import main
    from models import Profile
    absents = sorted({c for c in Profile.model_fields if c != "id"}
                     - set(main.ProfilePatch.model_fields))
    assert not absents, f"champs du modèle absents de ProfilePatch : {absents}"


def test_renommer_un_profil(client, admin_headers, profil_rempli):
    r = client.patch(f"/profiles/{profil_rempli.id}", headers=admin_headers,
                     json={"name": "Debian serveur — sans domaine"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Debian serveur — sans domaine"


def test_changer_l_OS_d_un_profil(client, admin_headers, profil_rempli):
    """Sans ça, dupliquer un profil Ubuntu pour Debian était impossible — et le
    profil restait invisible dans la liste au moment de créer une VM."""
    r = client.patch(f"/profiles/{profil_rempli.id}", headers=admin_headers,
                     json={"os": "debian"})
    assert r.status_code == 200, r.text
    assert r.json()["os"] == "debian"


def test_la_rotation_LAPS_est_bien_ENREGISTREE(client, admin_headers, profil_rempli):
    """Elle était affichée, modifiable, et silencieusement perdue."""
    r = client.patch(f"/profiles/{profil_rempli.id}", headers=admin_headers,
                     json={"laps_rotation_days": 30})
    assert r.status_code == 200, r.text
    with Session(engine) as s:
        assert s.get(Profile, profil_rempli.id).laps_rotation_days == 30


def test_un_OS_fantaisiste_est_REFUSE(client, admin_headers, profil_rempli):
    """Il ne casse rien tout de suite : il fait rendre le mauvais gabarit de
    premier démarrage des semaines plus tard, sur chaque machine du profil."""
    r = client.patch(f"/profiles/{profil_rempli.id}", headers=admin_headers,
                     json={"os": "archlinux"})
    assert r.status_code == 400
    assert "archlinux" in r.json()["detail"]
