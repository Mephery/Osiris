"""Tests d'intégration : authentification, JWT, clés API."""
from sqlmodel import Session
from models import engine, ApiKey
from auth import create_token
import hashlib, secrets


def test_login_credentials_valides(client, admin_user):
    r = client.post("/auth/login", json={"email": "admin@test.local", "password": "adminpass123"})
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["role"] == "admin"
    assert body["email"] == "admin@test.local"


def test_login_mauvais_mot_de_passe(client, admin_user):
    r = client.post("/auth/login", json={"email": "admin@test.local", "password": "mauvais"})
    assert r.status_code == 401


def test_login_email_inconnu(client):
    r = client.post("/auth/login", json={"email": "nobody@test.local", "password": "whatever"})
    assert r.status_code == 401


def test_me_sans_token_renvoie_401(client):
    r = client.get("/auth/me")
    assert r.status_code == 401


def test_me_avec_token_admin(client, admin_headers, admin_user):
    r = client.get("/auth/me", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == admin_user.email
    assert body["role"] == "admin"


def test_me_avec_token_technician(client, technician_headers, technician_user):
    r = client.get("/auth/me", headers=technician_headers)
    assert r.status_code == 200
    assert r.json()["role"] == "technician"


def test_token_invalide_renvoie_401(client):
    r = client.get("/auth/me", headers={"Authorization": "Bearer token.faux.invalide"})
    assert r.status_code == 401


def test_token_temp_totp_refuse_sur_me(client, admin_user):
    """Un token temporaire TOTP (scope=totp) ne doit pas donner accès aux routes normales."""
    from auth import create_temp_token
    temp = create_temp_token(str(admin_user.id))
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {temp}"})
    assert r.status_code == 401


def test_cle_api_valide(client, admin_user):
    """Une clé API doit permettre d'accéder aux routes protégées."""
    raw_key = "osiris_sk_" + secrets.token_hex(24)
    prefix = raw_key[:16]
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    with Session(engine) as session:
        session.add(ApiKey(user_id=admin_user.id, name="Test key", prefix=prefix, key_hash=key_hash))
        session.commit()
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {raw_key}"})
    assert r.status_code == 200
    assert r.json()["email"] == admin_user.email


def test_cle_api_invalide_renvoie_401(client, admin_user):
    r = client.get("/auth/me", headers={"Authorization": "Bearer osiris_sk_inexistante"})
    assert r.status_code == 401
