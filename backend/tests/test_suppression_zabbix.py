# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""La suppression d'une machine traite aussi son hôte Zabbix — au choix de
l'opérateur (cf. tests/test_zabbix_retrait.py pour la logique Zabbix elle-même).

Ici : le câblage. Le choix arrive bien jusqu'à Zabbix, un échec Zabbix ne
bloque pas la suppression mais est RAPPORTÉ, et un choix inconnu est refusé
AVANT de toucher à quoi que ce soit.
"""
from sqlmodel import Session, select

import zabbix
from models import AuditLog, Machine, engine

MAC = "aabbccddeeff"


def _fiche_existe() -> bool:
    with Session(engine) as session:
        return session.exec(select(Machine).where(Machine.mac == MAC)).first() is not None


def _hostname() -> str:
    with Session(engine) as session:
        return session.exec(select(Machine).where(Machine.mac == MAC)).first().hostname


def test_sans_choix_zabbix_n_est_pas_touche(client, test_machine, admin_headers, monkeypatch):
    """Comportement d'avant : l'API reste compatible avec un appel sans option."""
    appels = []
    monkeypatch.setattr(zabbix, "retirer_hote", lambda h, a: appels.append((h, a)) or "inchange")
    r = client.delete(f"/machines/{MAC}", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"zabbix": "inchange"}
    assert appels == [] or appels[0][1] == "rien"
    assert not _fiche_existe()


def test_le_choix_arrive_jusqu_a_zabbix(client, test_machine, admin_headers, monkeypatch):
    hostname = _hostname()
    appels = []
    monkeypatch.setattr(zabbix, "retirer_hote", lambda h, a: appels.append((h, a)) or "desactive")
    r = client.delete(f"/machines/{MAC}?zabbix=desactiver", headers=admin_headers)
    assert r.status_code == 200 and r.json() == {"zabbix": "desactive"}
    assert appels == [(hostname, "desactiver")]
    with Session(engine) as session:
        audit = session.exec(select(AuditLog).where(AuditLog.action == "delete_machine")).first()
    assert audit and "desactive" in str(audit.details)


def test_un_echec_zabbix_n_empeche_pas_la_suppression_mais_se_dit(client, test_machine,
                                                                  admin_headers, monkeypatch):
    """La VM est peut-être déjà détruite : garder une fiche sans VM serait pire.
    Mais l'opérateur doit savoir que l'hôte, lui, est resté."""
    def refus(h, a):
        raise RuntimeError("le rôle Zabbix du jeton OSIRIS n'autorise pas host.delete")
    monkeypatch.setattr(zabbix, "retirer_hote", refus)
    r = client.delete(f"/machines/{MAC}?zabbix=supprimer", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["zabbix"].startswith("echec:") and "host.delete" in r.json()["zabbix"]
    assert not _fiche_existe()


def test_un_choix_inconnu_est_refuse_avant_toute_suppression(client, test_machine, admin_headers):
    r = client.delete(f"/machines/{MAC}?zabbix=detruire", headers=admin_headers)
    assert r.status_code == 422
    assert _fiche_existe()


def test_l_etat_zabbix_pour_la_fenetre(client, test_machine, admin_headers, monkeypatch):
    hostname = _hostname()
    monkeypatch.setattr(zabbix, "etat_hote",
                        lambda h: {"configure": True, "existe": True, "gere": True,
                                   "actif": True, "groupes": ["OSIRIS-deployes"], "vu": h})
    r = client.get(f"/machines/{MAC}/zabbix", headers=admin_headers)
    assert r.status_code == 200 and r.json()["vu"] == hostname


def test_l_etat_zabbix_est_reserve_aux_admins(client, test_machine, technician_headers):
    assert client.get(f"/machines/{MAC}/zabbix", headers=technician_headers).status_code == 403
