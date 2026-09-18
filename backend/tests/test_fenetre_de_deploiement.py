# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Les scripts de déploiement ne sont servis QUE pendant le déploiement.

Ils portent en clair le compte de jonction au domaine, le mot de passe BIOS, le
Wi-Fi, et sont servis sans authentification à qui connaît une MAC. Ils restaient
servis à vie : le 18/09, le script d'un PC déployé le 07/07 sortait encore,
identifiants compris.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, select

from models import DeploymentEvent, Machine, engine

MAC = "aabbccddee10"
ROUTES = ["/firstboot-windows/{}", "/firstboot-linux/{}", "/unattend.xml?mac={}",
          "/preseed/{}", "/cloud-init/{}/user-data"]


def _machine(**kw):
    champs = dict(mac=MAC, hostname="PC-10", client="c", os="windows", status="pending",
                  password_hash="$6$x")
    champs.update(kw)
    with Session(engine) as s:
        s.add(Machine(**champs))
        s.commit()


def _codes(client):
    return {r: client.get(r.format(MAC)).status_code for r in ROUTES}


def test_pendant_le_deploiement_tout_est_servi(client, clean_db):
    _machine()
    assert all(c == 200 for c in _codes(client).values()), _codes(client)


def test_le_cas_du_18_09_une_machine_deployee_depuis_des_semaines(client, clean_db):
    _machine(status="deployed", smoke_status="ok",
             deployed_at=datetime.now(timezone.utc) - timedelta(days=73))
    assert all(c == 410 for c in _codes(client).values()), _codes(client)


def test_la_fin_des_smoke_tests_ferme_la_fenetre(client, clean_db):
    _machine(status="deployed", deployed_at=datetime.now(timezone.utc))
    client.post(f"/machines/{MAC}/smoke-tests", json={"tests": [{"name": "x", "ok": True}]})
    assert client.get(f"/firstboot-windows/{MAC}").status_code == 410


def test_installation_PXE_le_premier_demarrage_vient_apres_deployed(client, clean_db):
    """L'installeur PXE se déclare « deployed » AVANT le premier démarrage, qui
    vient ensuite chercher son script : il doit encore l'obtenir."""
    _machine(status="deployed", deployed_at=datetime.now(timezone.utc) - timedelta(hours=1))
    assert client.get(f"/firstboot-windows/{MAC}").status_code == 200


def test_sans_smoke_tests_la_fenetre_ne_reste_pas_ouverte_indefiniment(client, clean_db):
    _machine(status="deployed", deployed_at=datetime.now(timezone.utc) - timedelta(days=2))
    assert client.get(f"/firstboot-windows/{MAC}").status_code == 410


@pytest.mark.parametrize("age,code", [(timedelta(hours=3), 200), (timedelta(days=30), 410)])
def test_apres_un_echec_le_temps_de_relancer_a_la_main(client, clean_db, age, code):
    _machine(status="failed")
    with Session(engine) as s:
        s.add(DeploymentEvent(mac=MAC, hostname="PC-10", status="failed", os="windows",
                              profile_name="", timestamp=datetime.now(timezone.utc) - age))
        s.commit()
    assert client.get(f"/firstboot-windows/{MAC}").status_code == code


def test_un_redeploiement_rouvre_la_fenetre(client, admin_headers, clean_db):
    _machine(status="deployed", smoke_status="ok",
             deployed_at=datetime.now(timezone.utc) - timedelta(days=73))
    assert client.get(f"/firstboot-windows/{MAC}").status_code == 410
    client.post(f"/machines/{MAC}/redeploy-now", headers=admin_headers)
    assert client.get(f"/firstboot-windows/{MAC}").status_code == 200
    with Session(engine) as s:
        assert s.exec(select(Machine).where(Machine.mac == MAC)).one().smoke_status == ""


def test_le_refus_dit_quoi_faire(client, clean_db):
    _machine(status="deployed", smoke_status="ok", deployed_at=datetime.now(timezone.utc) - timedelta(days=5))
    assert "Redéployer" in client.get(f"/firstboot-windows/{MAC}").json()["detail"]


# ── Rouvrir la fenêtre, ou écraser les données de secours, sans compte ────────

def _deployee(**kw):
    _machine(status="deployed", smoke_status="ok",
             deployed_at=datetime.now(timezone.utc) - timedelta(days=30), **kw)


@pytest.mark.parametrize("statut", ["deploying", "failed", "deployed"])
def test_un_anonyme_ne_rouvre_pas_la_fenetre_par_le_statut(client, clean_db, statut):
    """Sans ce verrou, poster « deploying » sur une machine déployée rendait à
    nouveau servis ses scripts — identifiants compris."""
    _deployee()
    assert client.post(f"/machines/{MAC}/status?status={statut}").status_code == 409
    assert client.get(f"/firstboot-windows/{MAC}").status_code == 410


def test_pendant_le_deploiement_la_machine_rapporte_son_statut(client, clean_db):
    _machine()
    assert client.post(f"/machines/{MAC}/status?status=deploying").status_code == 200


def test_un_operateur_garde_la_main_sur_le_statut(client, admin_headers, clean_db):
    _deployee()
    assert client.post(f"/machines/{MAC}/status?status=failed", headers=admin_headers).status_code == 200


def test_une_cle_bitlocker_conservee_ne_s_ecrase_pas_hors_deploiement(client, clean_db):
    """Écrasée, elle rendait le disque irrécupérable le jour où on en aurait besoin."""
    from crypto import encrypt
    _deployee(bitlocker_key=encrypt("111111-222222"))
    assert client.post(f"/machines/{MAC}/bitlocker-key", json={"key": "faux"}).status_code == 409


def test_une_premiere_cle_bitlocker_est_toujours_acceptee(client, clean_db):
    _deployee()
    assert client.post(f"/machines/{MAC}/bitlocker-key", json={"key": "111111"}).status_code == 200


def _profil_rotation(jours):
    from models import Profile
    with Session(engine) as s:
        p = Profile(name="P", os="windows", laps_rotation_days=jours)
        s.add(p)
        s.commit()
        return p.id


def test_le_mot_de_passe_LAPS_ne_s_ecrase_pas_avant_l_echeance(client, clean_db):
    from crypto import encrypt
    _deployee(laps_password=encrypt("vrai"), profile_id=_profil_rotation(30),
              laps_rotated_at=datetime.now(timezone.utc) - timedelta(days=2))
    assert client.post(f"/machines/{MAC}/laps-password", json={"password": "faux"}).status_code == 409


def test_la_rotation_LAPS_due_est_acceptee(client, clean_db):
    """Le script de rotation poste bien après le déploiement : il doit passer."""
    from crypto import encrypt
    _deployee(laps_password=encrypt("ancien"), profile_id=_profil_rotation(30),
              laps_rotated_at=datetime.now(timezone.utc) - timedelta(days=31))
    assert client.post(f"/machines/{MAC}/laps-password", json={"password": "nouveau"}).status_code == 200
