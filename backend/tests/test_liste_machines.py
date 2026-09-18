# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Ce que la liste des machines doit porter pour que ses filtres disent vrai.

`smoke_status` n'y figurait pas : le filtre « Alertes smoke » et son compteur ne
trouvaient donc jamais rien. Et rien ne disait depuis quand une machine était
dans son statut — « en attente » depuis dix minutes ou depuis trois semaines se
ressemblaient.
"""
import json
from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from models import DeploymentEvent, Machine, engine

MAC = "aabbccddee40"


def _liste(client, headers):
    return next(m for m in client.get("/machines", headers=headers).json() if m["mac"] == MAC)


def test_la_liste_porte_les_resultats_des_tests(client, admin_headers, clean_db):
    with Session(engine) as s:
        s.add(Machine(mac=MAC, hostname="PC-40", client="c", os="ubuntu", status="deployed",
                      smoke_status="warnings",
                      smoke_results=json.dumps([{"name": "SSH", "ok": True},
                                                {"name": "Agent Zabbix", "ok": False}])))
        s.commit()
    m = _liste(client, admin_headers)
    assert m["smoke_status"] == "warnings"
    assert m["tests_en_echec"] == ["Agent Zabbix"]


def test_statut_depuis_suit_le_dernier_evenement(client, admin_headers, clean_db):
    il_y_a_3_semaines = datetime.now(timezone.utc) - timedelta(days=21)
    hier = datetime.now(timezone.utc) - timedelta(days=1)
    with Session(engine) as s:
        s.add(Machine(mac=MAC, hostname="PC-40", client="c", os="ubuntu", status="pending",
                      created_at=il_y_a_3_semaines))
        s.add(DeploymentEvent(mac=MAC, hostname="PC-40", status="pending", os="ubuntu",
                              profile_name="", timestamp=hier))
        s.commit()
    depuis = datetime.fromisoformat(_liste(client, admin_headers)["statut_depuis"])
    assert abs((depuis - hier).total_seconds()) < 5


def test_un_redeploiement_date_le_nouveau_statut(client, admin_headers, clean_db, monkeypatch):
    """Sans évènement, une machine tout juste redéployée paraissait bloquée depuis
    son déploiement précédent."""
    import main

    async def rien(*a):
        pass
    monkeypatch.setattr(main, "_orienter_boot_vm_windows", rien)
    with Session(engine) as s:
        s.add(Machine(mac=MAC, hostname="PC-40", client="c", os="ubuntu", status="deployed",
                      created_at=datetime.now(timezone.utc) - timedelta(days=60)))
        s.commit()
    client.post(f"/machines/{MAC}/redeploy-now", headers=admin_headers)
    depuis = datetime.fromisoformat(_liste(client, admin_headers)["statut_depuis"])
    assert datetime.now(timezone.utc) - depuis < timedelta(minutes=1)
