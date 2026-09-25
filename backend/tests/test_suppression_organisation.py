# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Supprimer une organisation encore utilisée doit être refusé, et dire pourquoi.

La base refusait déjà (clés étrangères), mais l'API répondait par un 500 opaque,
et l'interface annonçait « Organisation supprimée » sur une organisation qui
était toujours là.
"""
from sqlmodel import Session

from models import DomainConfig, Machine, Organization, engine


def _org(nom="Acme", slug="acme") -> int:
    with Session(engine) as session:
        o = Organization(name=nom, slug=slug)
        session.add(o)
        session.commit()
        session.refresh(o)
        return o.id


def test_une_organisation_libre_se_supprime(client, admin_headers):
    org = _org()
    assert client.delete(f"/organizations/{org}", headers=admin_headers).status_code == 204
    with Session(engine) as session:
        assert session.get(Organization, org) is None


def test_une_organisation_utilisee_est_refusee_avec_la_raison(client, admin_headers):
    org = _org()
    with Session(engine) as session:
        session.add(Machine(mac="aabbccddeeff", hostname="PC-01", client="Acme",
                            os="ubuntu", organization_id=org))
        session.add(DomainConfig(organization_id=org, name="AD", domain="acme.test"))
        session.commit()

    resp = client.delete(f"/organizations/{org}", headers=admin_headers)

    assert resp.status_code == 409
    assert "1 machine(s)" in resp.json()["detail"]
    assert "1 domaine(s) AD" in resp.json()["detail"]
    with Session(engine) as session:
        assert session.get(Organization, org) is not None
