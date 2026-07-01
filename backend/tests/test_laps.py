"""Tests d'intégration : calcul de rotation LAPS (GET /machines/{mac}/laps-due)."""
from datetime import datetime, timedelta, timezone
from sqlmodel import Session
from models import engine, Machine, Profile


def _make_machine(mac, profile_id=None, deployed_at=None, laps_rotated_at=None):
    with Session(engine) as s:
        m = Machine(mac=mac, hostname="PC-LAPS", client="Test", os="windows",
                    profile_id=profile_id, deployed_at=deployed_at,
                    laps_rotated_at=laps_rotated_at)
        s.add(m)
        s.commit()
        s.refresh(m)
        return m


def _make_profile(rotation_days):
    with Session(engine) as s:
        p = Profile(name=f"Profil {rotation_days}j", os="windows",
                    laps_rotation_days=rotation_days)
        s.add(p)
        s.commit()
        s.refresh(p)
        return p


def test_laps_due_mac_inconnue(client):
    r = client.get("/machines/aabbccddeeff/laps-due")
    assert r.status_code == 200
    assert r.json()["due"] is False


def test_laps_due_machine_sans_profil(client):
    _make_machine("001122334455")
    r = client.get("/machines/001122334455/laps-due")
    assert r.json()["due"] is False


def test_laps_due_rotation_desactivee(client):
    p = _make_profile(rotation_days=0)
    _make_machine("aabbcc001122", profile_id=p.id)
    r = client.get("/machines/aabbcc001122/laps-due")
    assert r.json()["due"] is False


def test_laps_due_jamais_effectuee_et_aucune_date(client):
    """Aucune date de rotation ni de déploiement -> rotation due immédiatement."""
    p = _make_profile(rotation_days=30)
    _make_machine("aabbcc002233", profile_id=p.id)
    r = client.get("/machines/aabbcc002233/laps-due")
    assert r.json()["due"] is True


def test_laps_due_periode_ecoulee(client):
    p = _make_profile(rotation_days=30)
    deployed = datetime.now(timezone.utc) - timedelta(days=40)
    _make_machine("aabbcc003344", profile_id=p.id, deployed_at=deployed)
    r = client.get("/machines/aabbcc003344/laps-due")
    assert r.json()["due"] is True


def test_laps_due_periode_non_ecoulee(client):
    p = _make_profile(rotation_days=30)
    deployed = datetime.now(timezone.utc) - timedelta(days=5)
    _make_machine("aabbcc004455", profile_id=p.id, deployed_at=deployed)
    r = client.get("/machines/aabbcc004455/laps-due")
    assert r.json()["due"] is False


def test_laps_due_se_base_sur_laps_rotated_at_pas_deployed_at(client):
    """laps_rotated_at (rotation récente) doit primer sur deployed_at (ancien)."""
    p = _make_profile(rotation_days=30)
    deployed = datetime.now(timezone.utc) - timedelta(days=100)   # très ancien
    last_rotation = datetime.now(timezone.utc) - timedelta(days=5) # récent
    _make_machine("aabbcc005566", profile_id=p.id,
                  deployed_at=deployed, laps_rotated_at=last_rotation)
    r = client.get("/machines/aabbcc005566/laps-due")
    assert r.json()["due"] is False  # rotation récente -> pas encore due
