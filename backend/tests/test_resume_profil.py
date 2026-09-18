# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Un profil doit dire ce qu'il fait AVANT qu'on déploie avec.

Deux profils Debian identiques à l'œil dans la liste, dont un seul donnait un
accès. Le second — serveur, aucune clé SSH, mot de passe SSH désactivé par le
durcissement, pas de mot de passe root — a déployé une machine où personne ne
pouvait entrer, et OSIRIS l'a déclarée réussie.

Le résumé est lu sur les mêmes conditions que les scripts de premier démarrage.
Les tests vérifient donc aussi qu'une DomainConfig liée est bien prise en compte
PAR LA ROUTE, pas seulement par la fonction : c'est le chemin que l'écran lit.
"""
from sqlmodel import Session

import main
from crypto import encrypt
from models import DomainConfig, Profile, engine


def _profil(**kw) -> Profile:
    champs = dict(name="P", os="debian", machine_type="server", default_user="humans",
                  join_domain=False, ssh_authorized_keys="", set_root_password=False)
    champs.update(kw)
    with Session(engine) as s:
        p = Profile(**champs)
        s.add(p)
        s.commit()
        s.refresh(p)
        return p


def _resume(p: Profile) -> dict:
    with Session(engine) as s:
        return main._profile_summary(s.get(Profile, p.id), s)


def _texte(resume: dict, sujet: str) -> str:
    return next(l["texte"] for l in resume["lignes"] if l["sujet"] == sujet)


def test_le_profil_qui_a_enferme_dehors_est_signale(clean_db):
    """Le cas du 17/09, tel quel."""
    r = _resume(_profil())
    assert r["alerte"], "un profil sans aucun accès doit le dire"
    assert _texte(r, "SSH") == "aucune clé"


def test_une_cle_suffit_a_lever_l_alerte(clean_db):
    r = _resume(_profil(ssh_authorized_keys="ssh-ed25519 AAAAx a@b\n# commentaire\n\nssh-rsa AAAAy c@d"))
    assert r["alerte"] == ""
    # les commentaires et lignes vides ne sont pas des clés
    assert _texte(r, "SSH") == "par clé pour humans (2 clés)"


def test_le_mot_de_passe_root_de_secours_suffit(clean_db):
    assert _resume(_profil(set_root_password=True))["alerte"] == ""


def test_des_cles_sans_compte_ne_donnent_aucun_acces(clean_db):
    """Le firstboot n'écrit les clés que dans le home du compte local : sans
    compte, elles ne sont posées nulle part."""
    r = _resume(_profil(default_user="", ssh_authorized_keys="ssh-ed25519 AAAAx"))
    assert r["alerte"]
    assert "aucun compte" in _texte(r, "SSH")


def test_une_jonction_sans_compte_n_est_pas_un_acces(clean_db):
    r = _resume(_profil(join_domain=True, domain="corp.local"))
    assert r["alerte"]
    assert "hors domaine" in _texte(r, "Domaine")


def test_le_compte_de_jonction_de_la_domain_config_compte_via_la_route(
        client, admin_headers, clean_db):
    """Profil sans compte de jonction, mais lié à une DomainConfig qui en a un :
    la machine JOINDRA. Le résumé servi à l'écran doit le savoir."""
    with Session(engine) as s:
        dc = DomainConfig(organization_id=1, name="DC", domain="corp.local",
                          join_user="corp\\joiner", join_password=encrypt("x"))
        s.add(dc)
        s.commit()
        s.refresh(dc)
        dc_id = dc.id
    p = _profil(join_domain=True, domain="ancien.local", domain_config_id=dc_id)

    r = client.get("/profiles", headers=admin_headers)
    assert r.status_code == 200, r.text
    resume = next(x for x in r.json() if x["id"] == p.id)["resume"]
    assert resume["alerte"] == ""
    assert _texte(resume, "Domaine") == "joint corp.local"


def test_un_profil_windows_garde_toujours_un_administrateur(clean_db):
    """Le firstboot Windows pose toujours un mot de passe unique sur
    l'administrateur intégré et le remet à OSIRIS."""
    r = _resume(_profil(os="windows", default_user="", laps_rotation_days=30))
    assert r["alerte"] == ""
    assert "30 j" in _texte(r, "Accès")

