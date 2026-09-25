# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Le jeton d'une machine : ce qui prouve qu'un appel vient bien d'elle.

Connaître une MAC suffisait pour obtenir les scripts d'une machine (compte de
jonction AD, mot de passe BIOS…) et parler en son nom. Le jeton est remis dans
le premier script servi, puis exigé partout. Mode transition : absent = accepté
et consigné ; faux = toujours refusé.
"""
import re
import stat
import subprocess

import pytest
from sqlmodel import Session, select

import jetons
import main
from models import AuditLog, Machine, engine

MAC = "aabbccddeeff"


@pytest.fixture(autouse=True)
def signalements_oublies():
    """Les appels sans jeton ne sont consignés qu'une fois par déploiement, en
    mémoire : sans remise à zéro, un test précédent aurait déjà « signalé »."""
    main._sans_jeton_signales.clear()
    yield
    main._sans_jeton_signales.clear()


@pytest.fixture
def linux(test_machine):
    with Session(engine) as session:
        m = session.exec(select(Machine).where(Machine.mac == MAC)).first()
        m.os, m.status = "debian", "pending"
        session.add(m)
        session.commit()


def _script(client, jeton=None):
    return client.get(f"/firstboot-linux/{MAC}", headers={jetons.ENTETE: jeton} if jeton else {})


def _jeton_du(script: str) -> str:
    return re.search(r"^_osiris_jeton='([^']*)'", script, re.M).group(1)


def _audit(action: str) -> int:
    with Session(engine) as session:
        return len(session.exec(select(AuditLog).where(AuditLog.action == action)).all())


# ── Remise unique ─────────────────────────────────────────────────────────────

def test_la_premiere_demande_recoit_le_jeton(client, linux):
    r = _script(client)
    assert r.status_code == 200
    jeton = _jeton_du(r.text)
    assert len(jeton) >= 40
    with Session(engine) as session:
        fiche = session.exec(select(Machine).where(Machine.mac == MAC)).first()
    assert fiche.jeton_hash == jetons.empreinte(jeton), "seule l'empreinte est en base"
    assert jeton not in fiche.jeton_hash


def test_le_jeton_n_est_remis_qu_une_fois(client, linux):
    """Transition : la deuxième demande SANS jeton est servie, mais sans le jeton,
    et consignée — un tiers qui connaît la MAC n'obtient plus le secret."""
    premier = _jeton_du(_script(client).text)
    r = _script(client)
    assert r.status_code == 200
    assert _jeton_du(r.text) == "" and premier not in r.text
    assert _audit("appel_sans_jeton") == 1


def test_la_machine_recharge_son_script_avec_son_jeton(client, linux):
    jeton = _jeton_du(_script(client).text)
    r = _script(client, jeton)
    assert r.status_code == 200 and _jeton_du(r.text) == jeton


def test_un_jeton_faux_est_toujours_refuse(client, linux):
    _script(client)
    r = _script(client, "faux-jeton")
    assert r.status_code == 403
    assert _audit("jeton_refuse") == 1


def test_un_redeploiement_change_le_jeton(client, linux):
    ancien = _jeton_du(_script(client).text)
    with Session(engine) as session:
        m = session.exec(select(Machine).where(Machine.mac == MAC)).first()
        main._open_new_deploy_run(m)
        session.add(m)
        session.commit()
    nouveau = _jeton_du(_script(client).text)
    assert nouveau and nouveau != ancien
    assert _script(client, ancien).status_code == 403


# ── Les rappels de la machine ─────────────────────────────────────────────────

RAPPELS = [
    ("post", f"/machines/{MAC}/log", {"params": {"msg": "coucou"}}),
    ("post", f"/machines/{MAC}/hardware", {"json": {"serial": "x"}}),
    ("post", f"/machines/{MAC}/smoke-tests", {"json": {"tests": []}}),
    ("post", f"/machines/{MAC}/deploy-progress", {"params": {"p": 10}}),
    ("post", f"/machines/{MAC}/status", {"params": {"status": "deploying"}}),
    ("get", f"/machines/{MAC}/laps-due", {}),
]


@pytest.mark.parametrize("methode, url, kw", RAPPELS)
def test_un_rappel_avec_un_jeton_faux_est_refuse(client, linux, methode, url, kw):
    _script(client)
    r = getattr(client, methode)(url, headers={jetons.ENTETE: "faux"}, **kw)
    assert r.status_code == 403, url


@pytest.mark.parametrize("methode, url, kw", RAPPELS)
def test_un_rappel_avec_le_bon_jeton_passe(client, linux, methode, url, kw):
    jeton = _jeton_du(_script(client).text)
    r = getattr(client, methode)(url, headers={jetons.ENTETE: jeton}, **kw)
    assert r.status_code != 403, url


def test_un_rappel_sans_jeton_passe_en_transition(client, linux):
    _script(client)
    assert client.post(f"/machines/{MAC}/log", params={"msg": "ancien agent"}).status_code == 200


def test_le_mode_obligatoire_refuse_l_absence(client, linux, monkeypatch):
    jeton = _jeton_du(_script(client).text)
    monkeypatch.setenv("OSIRIS_JETON_OBLIGATOIRE", "1")
    assert client.post(f"/machines/{MAC}/log", params={"msg": "x"}).status_code == 403
    assert _script(client).status_code == 403, "le script ne se ressert plus sans jeton"
    assert client.post(f"/machines/{MAC}/log", params={"msg": "x"},
                       headers={jetons.ENTETE: jeton}).status_code == 200


def test_un_operateur_connecte_n_a_pas_besoin_du_jeton(client, linux, admin_headers, monkeypatch):
    monkeypatch.setenv("OSIRIS_JETON_OBLIGATOIRE", "1")
    r = client.post(f"/machines/{MAC}/status", params={"status": "deploying"}, headers=admin_headers)
    assert r.status_code != 403


# ── Côté script : le jeton ne part que vers OSIRIS ────────────────────────────

def test_le_jeton_ne_part_que_vers_osiris(tmp_path, client, linux):
    """Le smoke test d'accès internet joint un site extérieur : il ne doit pas
    recevoir le jeton."""
    script = _script(client).text
    bloc = script[script.index("_osiris_jeton="):script.index("\n# Garde pour l'agent")]
    faux = tmp_path / "curl"
    faux.write_text('#!/bin/bash\necho "CURL $*"\n')
    faux.chmod(faux.stat().st_mode | stat.S_IEXEC)
    corps = f'osiris_url="http://osiris.test"\n{bloc}\ncurl -s http://osiris.test/machines/x/log\ncurl -s https://www.example.com/'
    r = subprocess.run(["bash", "-c", corps], text=True, capture_output=True,
                       env={"PATH": f"{tmp_path}:/usr/bin:/bin"})
    vers_osiris, vers_dehors = r.stdout.strip().splitlines()
    assert "X-Osiris-Jeton" in vers_osiris
    assert "X-Osiris-Jeton" not in vers_dehors


# ── Création d'une VM ─────────────────────────────────────────────────────────

def test_sur_proxmox_le_jeton_attend_la_premiere_demande(client, admin_headers, monkeypatch):
    """Le cloud-init n'arrive pas dans une VM Proxmox : un jeton créé d'avance ne
    lui parviendrait jamais, et la remise unique ne se ferait plus."""
    from tests.test_create_vm import _make_hypervisor, _patch_proxmox
    hv_id = _make_hypervisor()
    _patch_proxmox(monkeypatch, {})
    resp = client.post(f"/hypervisors/{hv_id}/create-vm", headers=admin_headers, json={
        "hostname": "srv-jeton", "client": "Acme", "os": "debian", "node": "pve",
        "storage": "ceph", "boot_mode": "pxe"})
    assert resp.status_code == 201, resp.text
    with Session(engine) as session:
        fiche = session.exec(select(Machine).where(Machine.hostname == "srv-jeton")).first()
    assert fiche.jeton_hash == ""
