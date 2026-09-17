# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Changer un mot de passe ne laissait aucune trace.

C'est pourtant le geste qu'on veut pouvoir dater : c'est ce que fait un
opérateur après une fuite, et c'est aussi exactement ce que fait quelqu'un qui
vient de prendre un compte et veut y rester. Sans entrée d'audit, les deux cas
se ressemblent — on ne voit qu'une connexion.

Constaté le 17/09 en vérifiant un changement de mot de passe réel : l'audit ne
contenait que la connexion qui l'avait précédé.
"""
from sqlmodel import Session, select

from models import AuditLog, engine


def _actions(email: str) -> list[str]:
    with Session(engine) as s:
        return [a.action for a in s.exec(
            select(AuditLog).where(AuditLog.user_email == email)
            .order_by(AuditLog.id)).all()]


def test_le_changement_de_mot_de_passe_est_journalise(client, admin_user, admin_headers):
    r = client.patch("/auth/me/password", headers=admin_headers, json={
        "current_password": "adminpass123",
        "new_password": "une phrase de passe bien plus longue",
    })
    assert r.status_code == 200, r.text
    assert "change_password" in _actions(admin_user.email)


def test_un_echec_ne_journalise_RIEN(client, admin_user, admin_headers):
    """Sinon l'audit dirait « mot de passe changé » alors qu'il ne l'a pas été —
    une trace fausse est pire qu'une trace absente."""
    r = client.patch("/auth/me/password", headers=admin_headers, json={
        "current_password": "ce-n-est-pas-le-bon",
        "new_password": "une phrase de passe bien plus longue",
    })
    assert r.status_code == 401
    assert "change_password" not in _actions(admin_user.email)


def test_un_mot_de_passe_refuse_ne_journalise_RIEN(client, admin_user, admin_headers):
    """Refusé par la politique : rien n'a changé, l'audit ne doit rien affirmer."""
    r = client.patch("/auth/me/password", headers=admin_headers, json={
        "current_password": "adminpass123", "new_password": "court",
    })
    assert r.status_code == 400
    assert "change_password" not in _actions(admin_user.email)


def test_l_audit_ne_contient_PAS_le_mot_de_passe(client, admin_user, admin_headers):
    """La ligne dit QUI et QUAND. Le secret n'a rien à faire dans un journal que
    tout administrateur peut relire."""
    secret = "une phrase de passe bien plus longue"
    client.patch("/auth/me/password", headers=admin_headers,
                 json={"current_password": "adminpass123", "new_password": secret})
    with Session(engine) as s:
        lignes = s.exec(select(AuditLog).where(
            AuditLog.user_email == admin_user.email)).all()
    for l in lignes:
        assert secret not in (l.details or "")
        assert secret not in (l.target_mac or "")
