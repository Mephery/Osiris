# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
# Configuration et fixtures partagées pour tous les tests OSIRIS.
# Les env vars doivent être posées AVANT tout import de models/main/auth,
# car engine est un global de module créé à l'import.
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./osiris_test.db")
os.environ.setdefault("JWT_SECRET", "osiris-test-secret-not-for-production")
os.environ.setdefault("FERNET_KEY", "o0iGmcXE-Q8vzulvt4mQHHuCAIy0JyZwD8bmskK5J5I=")
os.environ.setdefault("ADMIN_EMAIL", "admin@osiris.test")
os.environ.setdefault("ADMIN_PASSWORD", "testadminpass")
os.environ.setdefault("OSIRIS_BASE_URL", "http://localhost:8000")
os.environ.setdefault("OSIRIS_IP", "127.0.0.1")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session

from sqlmodel import Session as _BaseSession
from models import engine, User, Machine, Profile, Organization
from auth import hash_password, create_token

def Session(bind):
    """Session avec expire_on_commit=False pour retourner des objets vivants hors session."""
    return _BaseSession(bind, expire_on_commit=False)


# ── Lifecycle de la base de test ───────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def _create_tables():
    """Crée toutes les tables une seule fois pour la session de tests."""
    SQLModel.metadata.create_all(engine)
    yield
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def clean_db(_create_tables):
    """Vide toutes les tables avant chaque test (ordre FK respecté)."""
    with engine.connect() as conn:
        for table in reversed(SQLModel.metadata.sorted_tables):
            conn.execute(table.delete())
        conn.commit()


# ── Client HTTP ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def client():
    from main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Fixtures utilisateurs ──────────────────────────────────────────────────────

@pytest.fixture
def admin_user(clean_db):
    with Session(engine) as session:
        user = User(
            email="admin@test.local",
            hashed_password=hash_password("adminpass123"),
            role="admin",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


@pytest.fixture
def admin_token(admin_user):
    return create_token({"sub": str(admin_user.id), "role": admin_user.role, "email": admin_user.email})


@pytest.fixture
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def technician_user(clean_db):
    with Session(engine) as session:
        user = User(
            email="tech@test.local",
            hashed_password=hash_password("techpass123"),
            role="technician",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


@pytest.fixture
def technician_token(technician_user):
    return create_token({"sub": str(technician_user.id), "role": technician_user.role, "email": technician_user.email})


@pytest.fixture
def technician_headers(technician_token):
    return {"Authorization": f"Bearer {technician_token}"}


# ── Fixtures métier ────────────────────────────────────────────────────────────

@pytest.fixture
def test_profile(clean_db):
    with Session(engine) as session:
        profile = Profile(name="Profil test", os="windows", locale="fr-FR",
                          laps_rotation_days=30)
        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile


@pytest.fixture
def test_machine(clean_db, test_profile):
    with Session(engine) as session:
        machine = Machine(
            mac="aabbccddeeff",
            hostname="PC-TEST",
            client="Client Test",
            os="windows",
            profile_id=test_profile.id,
        )
        session.add(machine)
        session.commit()
        session.refresh(machine)
        return machine


@pytest.fixture(autouse=True)
def limiteur_remis_a_zero():
    """
    Remet le limiteur de débit à zéro entre chaque test.

    Il est porté par l'application, donc partagé par toute la suite, et sa clé en
    test est toujours la même (« testclient »). Les compteurs s'additionnaient
    ainsi d'un test à l'autre : `/machines/{mac}/status` est plafonné à 10/minute,
    et la suite ne passait que tant qu'elle restait sous ce seuil par hasard.
    Ajouter deux tests suffisait à faire répondre 429 à un test parfaitement
    innocent — et à un endroit sans rapport avec la cause.
    """
    import main   # importé ici : conftest règle l'environnement avant que main charge
    main.limiter.reset()
    yield


# ── Identité des VM ────────────────────────────────────────────────────────────
# `proxmox_vm_id` est un entier RECYCLÉ par Proxmox, pas une identité : OSIRIS
# relit donc `/config` et compare une ancre non recyclable (l'UUID SMBIOS) avant
# toute écriture sur une VM. Tout faux Proxmox doit savoir répondre à cet appel —
# sinon l'action est refusée, ce qui est exactement le comportement attendu en
# production quand la fiche et l'hyperviseur ont divergé.

UUID_VM_TEST = "12345678-1234-1234-1234-1234567890ab"


def config_vm_conforme(nom: str = "PC-TEST", uuid_vm: str = UUID_VM_TEST) -> dict:
    """Config Proxmox d'une VM dont l'identité correspond à la fiche de test."""
    return {"name": nom, "smbios1": f"uuid={uuid_vm}", "boot": "order=ide2;sata0"}


def config_vm_etrangere() -> dict:
    """Config d'une VM ayant hérité du même numéro : OSIRIS doit refuser d'y toucher."""
    return {"name": "SRV-PROD-CLIENT", "smbios1": "uuid=99999999-9999-9999-9999-999999999999"}
