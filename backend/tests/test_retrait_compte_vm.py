# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Retirer de la fiche le compte de la personne d'une VM.

Le compte est relu par le premier démarrage, y compris à chaque redéploiement.
Supprimé ou remplacé à la main sur la machine (le compte `runner` remplacé par
`dev` le 09/10), il restait sur la fiche — et un redéploiement l'aurait recréé,
avec sa clé et son sudo complet, sans que rien ne le montre : la fiche ne
l'affichait même pas.
"""
import json

from sqlmodel import Session, select

import main
from models import AuditLog, Machine, engine

MAC = "aabbcc000020"
CLE = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOJMLT5FY7PGlhMRilTN7PKYnQ1zZb6V0JHZJo0GGYcl x"


def _machine():
    with Session(engine) as s:
        s.add(Machine(mac=MAC, client="Acme", os="debian", hostname="vm-compte",
                      compte=json.dumps({"nom": "runner", "cle_ssh": CLE, "sudo": True})))
        s.commit()


def test_la_fiche_montre_le_compte_sans_jamais_sa_cle(client, admin_headers):
    _machine()
    m = next(m for m in client.get("/machines", headers=admin_headers).json() if m["mac"] == MAC)
    assert m["compte_vm"] == {"nom": "runner", "sudo": True}
    assert "AAAA" not in json.dumps(m)


def test_le_retrait_vide_la_fiche_et_laisse_une_trace(client, admin_headers):
    _machine()
    r = client.delete(f"/machines/{MAC}/compte", headers=admin_headers)
    assert r.status_code == 204, r.text
    with Session(engine) as s:
        assert s.exec(select(Machine)).first().compte == ""
        audit = s.exec(select(AuditLog).where(AuditLog.action == "retirer_compte_vm")).first()
        assert audit and "runner" in (audit.details or "")
    m = next(m for m in client.get("/machines", headers=admin_headers).json() if m["mac"] == MAC)
    assert m["compte_vm"] is None


def test_un_redeploiement_ne_recree_plus_le_compte(client, admin_headers):
    _machine()
    client.delete(f"/machines/{MAC}/compte", headers=admin_headers)
    with Session(engine) as s:
        m = s.exec(select(Machine)).first()
        script = main._firstboot_linux_content(
            hostname=m.hostname, mac=MAC, ou="",
            profile_ctx={"os": "debian", "default_user": "humans", "join_domain": False,
                         "app_ids": "", "tv_suffix": "", "vm_data_disk_gb": 0},
            linux_apps=[], zabbix=None, osiris_url="http://osiris.test",
            compte=json.loads(m.compte) if m.compte else None)
    assert "runner" not in script


def test_reserve_aux_administrateurs(client):
    _machine()
    assert client.delete(f"/machines/{MAC}/compte").status_code in (401, 403)


def test_machine_inconnue(client, admin_headers):
    assert client.delete("/machines/aabbcc000099/compte", headers=admin_headers).status_code == 404
