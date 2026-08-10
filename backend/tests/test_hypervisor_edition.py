# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Modification d'un hyperviseur déjà enregistré.

Il n'existait aucun moyen de le faire : l'interface savait créer, tester et
supprimer, rien d'autre. Tout champ ajouté après coup restait donc hors d'atteinte
sur les fiches existantes — alors que ce sont précisément celles-là qu'il faut
corriger. Constaté le 2026-08-10 avec le champ `pool`, ajouté pour borner les
droits du jeton et impossible à renseigner sur les trois hyperviseurs en place.
"""
from sqlmodel import Session, select

from crypto import decrypt, encrypt
from models import Hypervisor, engine


def _fiche(**o) -> int:
    base = dict(name="pve-test", type="proxmox", url="https://pve.test:8006",
                token_id="osiris@pve!osiris", token_secret=encrypt("s3cret-original"))
    base.update(o)
    with Session(engine) as session:
        h = Hypervisor(**base)
        session.add(h)
        session.commit()
        session.refresh(h)
        return h.id


def test_le_pool_est_modifiable_sur_une_fiche_existante(client, admin_headers):
    """Le cas qui a bloqué la bascule des droits en production."""
    hv_id = _fiche(pool="")

    resp = client.patch(f"/hypervisors/{hv_id}", headers=admin_headers,
                        json={"pool": "osiris"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["pool"] == "osiris"
    with Session(engine) as session:
        assert session.get(Hypervisor, hv_id).pool == "osiris"


def test_le_secret_masque_nest_jamais_reecrit(client, admin_headers):
    """
    La fiche renvoie « *** » à la place du secret. Un client qui la relit puis la
    renvoie telle quelle chiffrerait ces trois étoiles : OSIRIS perdrait l'accès à
    l'hyperviseur, et la fiche paraîtrait pourtant remplie — panne muette.
    """
    hv_id = _fiche()

    resp = client.patch(f"/hypervisors/{hv_id}", headers=admin_headers,
                        json={"name": "pve-renomme", "token_secret": "***"})

    assert resp.status_code == 200, resp.text
    with Session(engine) as session:
        h = session.get(Hypervisor, hv_id)
    assert h.name == "pve-renomme", "le reste du patch doit bien s'appliquer"
    assert decrypt(h.token_secret) == "s3cret-original", "le secret devait rester intact"


def test_un_secret_vide_laisse_lancien_en_place(client, admin_headers):
    """Le formulaire envoie un champ vide quand l'opérateur n'y touche pas."""
    hv_id = _fiche()

    resp = client.patch(f"/hypervisors/{hv_id}", headers=admin_headers,
                        json={"token_secret": ""})

    assert resp.status_code == 200, resp.text
    with Session(engine) as session:
        h = session.get(Hypervisor, hv_id)
    assert decrypt(h.token_secret) == "s3cret-original"


def test_un_vrai_nouveau_secret_est_chiffre(client, admin_headers):
    hv_id = _fiche()

    resp = client.patch(f"/hypervisors/{hv_id}", headers=admin_headers,
                        json={"token_secret": "nouveau-s3cret"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["token_secret"] == "***", "jamais renvoyé en clair"
    with Session(engine) as session:
        h = session.get(Hypervisor, hv_id)
    assert h.token_secret != "nouveau-s3cret", "il doit être chiffré en base"
    assert decrypt(h.token_secret) == "nouveau-s3cret"


def test_la_verification_tls_est_activable_apres_coup(client, admin_headers):
    """L'autre champ que la bascule sécurité demande de corriger sur l'existant."""
    hv_id = _fiche(tls_verify=False)

    resp = client.patch(f"/hypervisors/{hv_id}", headers=admin_headers,
                        json={"tls_verify": True})

    assert resp.status_code == 200, resp.text
    assert resp.json()["tls_verify"] is True


def test_modifier_un_hyperviseur_exige_une_authentification(client):
    """La fiche porte un jeton qui peut détruire des VM : réservé aux admins."""
    hv_id = _fiche()

    assert client.patch(f"/hypervisors/{hv_id}", json={"pool": "osiris"}).status_code == 401


def test_la_modification_est_journalisee(client, admin_headers):
    from models import AuditLog

    hv_id = _fiche()
    client.patch(f"/hypervisors/{hv_id}", headers=admin_headers, json={"pool": "osiris"})

    with Session(engine) as session:
        trace = session.exec(
            select(AuditLog).where(AuditLog.action == "update_hypervisor")).first()
    assert trace is not None
