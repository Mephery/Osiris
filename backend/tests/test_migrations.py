# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""La chaîne Alembic doit aboutir sur une base VIERGE.

Régression visée : la 0001 fait un `SQLModel.metadata.create_all()`, donc sur une
base neuve elle crée *toutes* les tables déclarées dans models.py aujourd'hui —
y compris celles ajoutées bien plus tard. Toute migration ultérieure qui crée un
objet sans `IF NOT EXISTS` échoue alors en « la relation existe déjà », et
l'installation neuve est cassée sans que la base de production (déjà migrée) ne
montre quoi que ce soit. C'est exactement ce qui est arrivé à la 0006.

Ces tests ne tournent que si `OSIRIS_MIGRATION_TEST_DB` pointe vers une base
Postgres jetable — les migrations sont du Postgres pur (SERIAL, `ADD COLUMN IF
NOT EXISTS`, NOW()) et ne s'exécutent pas sur le SQLite du reste de la suite.
"""
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlmodel import SQLModel

import models  # noqa: F401 — peuple SQLModel.metadata

BACKEND_DIR = Path(__file__).resolve().parent.parent
TEST_DB_URL = os.environ.get("OSIRIS_MIGRATION_TEST_DB", "")

pytestmark = pytest.mark.skipif(
    not TEST_DB_URL,
    reason="OSIRIS_MIGRATION_TEST_DB non definie (base Postgres jetable requise)",
)


def _parts():
    """Éclate l'URL de test, et refuse tout ce qui ne ressemble pas à une base jetable.

    Garde-fou volontairement paranoïaque : ce test fait un `DROP SCHEMA public
    CASCADE`. Pointé par erreur sur la base de production, il détruirait tout.
    """
    u = urllib.parse.urlparse(TEST_DB_URL)
    name = u.path.lstrip("/")
    if "test" not in name:
        pytest.fail(
            f"OSIRIS_MIGRATION_TEST_DB vise la base '{name}', dont le nom ne contient "
            "pas 'test'. Refus : ce test efface le schema de la base qu'il vise."
        )
    return {
        "DB_USER": urllib.parse.unquote(u.username or ""),
        "DB_PASSWORD": urllib.parse.unquote(u.password or ""),
        "DB_HOST": u.hostname or "localhost",
        "DB_NAME": name,
    }


def _engine():
    # _parts() d'abord, toujours : c'est lui qui porte le garde-fou, et toute
    # connexion a cette base doit passer derriere. Le laisser au seul appelant
    # d'`_alembic` laissait `_wipe` faire son DROP SCHEMA sans verification.
    _parts()
    return sa.create_engine(TEST_DB_URL, poolclass=sa.pool.NullPool)


def _wipe():
    """Remet la base de test à zéro — l'état d'une installation neuve."""
    with _engine().connect() as conn:
        conn.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA public"))
        conn.commit()


def _alembic(*args):
    env = {**os.environ, **_parts()}
    # Surtout pas `python -m alembic...` : on s'execute depuis backend/, ou le
    # dossier de migrations `alembic/` masque le paquet installe. On appelle donc
    # le script console, a cote de l'interpreteur courant.
    exe = Path(sys.executable).parent / "alembic"
    return subprocess.run(
        [str(exe) if exe.exists() else "alembic", *args],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )


def _head_revision() -> str:
    """Derniere revision de la chaine, telle qu'Alembic la voit.

    Passe par la commande plutot que par un import : depuis backend/, le dossier
    de migrations `alembic/` masque le paquet installe (cf. `_alembic`).
    """
    res = _alembic("heads")
    assert res.returncode == 0, f"alembic heads en echec :\n{res.stderr}"
    return res.stdout.split()[0]


def test_upgrade_head_sur_base_vierge():
    """`alembic upgrade head` doit aboutir sur une base sans aucune table."""
    _wipe()
    res = _alembic("upgrade", "head")
    assert res.returncode == 0, (
        f"alembic upgrade head a echoue sur une base vierge :\n{res.stderr}"
    )

    with _engine().connect() as conn:
        version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
    assert version == _head_revision()


def test_schema_produit_correspond_aux_modeles():
    """Le schéma obtenu doit contenir toutes les tables et colonnes de models.py.

    Sinon la chaîne « aboutit » mais l'application casse au premier SELECT.
    """
    _wipe()
    assert _alembic("upgrade", "head").returncode == 0

    insp = sa.inspect(_engine())
    tables = set(insp.get_table_names()) - {"alembic_version"}

    manquantes = set(SQLModel.metadata.tables) - tables
    assert not manquantes, f"tables absentes du schema migre : {sorted(manquantes)}"

    for name, table in SQLModel.metadata.tables.items():
        colonnes = {c["name"] for c in insp.get_columns(name)}
        absentes = set(table.columns.keys()) - colonnes
        assert not absentes, f"{name} : colonnes absentes {sorted(absentes)}"


def test_upgrade_head_est_rejouable():
    """Rejouer la chaîne sur une base déjà à jour ne doit rien casser.

    C'est ce que fait le service au démarrage à chaque redémarrage d'OSIRIS.
    """
    _wipe()
    assert _alembic("upgrade", "head").returncode == 0
    res = _alembic("upgrade", "head")
    assert res.returncode == 0, f"second upgrade head en echec :\n{res.stderr}"
