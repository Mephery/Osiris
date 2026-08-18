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


def test_0027_ajoute_vraiment_ses_objets_sur_une_base_deja_migree():
    """La 0027 doit fonctionner en ALTER, pas seulement en no-op.

    Piège symétrique de celui de la 0006 : sur une base VIERGE, la 0001 fait un
    `create_all()` depuis models.py, donc `vm_uuid`, `pool` et l'index de
    réservation existent déjà quand la 0027 s'exécute — ses `IF NOT EXISTS` la
    rendent alors muette, et son vrai travail n'est jamais testé. Or en production
    la base est à la 0026 SANS ces objets : c'est le seul chemin qui compte, et il
    n'était couvert par rien.

    On le reconstitue : on monte à head, on retire les objets de la 0027, on
    redescend le marqueur de version, puis on rejoue.
    """
    _wipe()
    assert _alembic("upgrade", "head").returncode == 0

    with _engine().connect() as conn:
        conn.execute(sa.text("DROP INDEX IF EXISTS ix_machine_vm_reservation"))
        conn.execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS vm_uuid"))
        conn.execute(sa.text("ALTER TABLE hypervisor DROP COLUMN IF EXISTS pool"))
        conn.execute(sa.text("UPDATE alembic_version SET version_num = '0026'"))
        conn.commit()

    res = _alembic("upgrade", "head")
    assert res.returncode == 0, f"la 0027 echoue en ALTER :\n{res.stderr}"

    insp = sa.inspect(_engine())
    assert "vm_uuid" in {c["name"] for c in insp.get_columns("machine")}
    assert "pool" in {c["name"] for c in insp.get_columns("hypervisor")}
    index = {i["name"] for i in insp.get_indexes("machine")}
    assert "ix_machine_vm_reservation" in index


def test_0029_ajoute_vraiment_sa_colonne_sur_une_base_deja_migree():
    """Même piège que la 0027, et même remède.

    Sur une base vierge, la 0001 crée déjà `vm_bridge` depuis models.py : l'`IF NOT
    EXISTS` de la 0029 la rend muette et son vrai travail passe sous les radars. Le
    seul chemin qui compte en production part d'une base à la 0028, sans la colonne.
    """
    _wipe()
    assert _alembic("upgrade", "head").returncode == 0

    with _engine().connect() as conn:
        conn.execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS vm_bridge"))
        conn.execute(sa.text("UPDATE alembic_version SET version_num = '0028'"))
        conn.commit()

    res = _alembic("upgrade", "head")
    assert res.returncode == 0, f"la 0029 echoue en ALTER :\n{res.stderr}"

    insp = sa.inspect(_engine())
    assert "vm_bridge" in {c["name"] for c in insp.get_columns("machine")}


def test_0030_ajoute_vraiment_sa_colonne_sur_une_base_deja_migree():
    """Même piège que les 0027 et 0029 : sur une base vierge la 0001 crée déjà la
    colonne, et l'`IF NOT EXISTS` masque le seul chemin qui compte en production."""
    _wipe()
    assert _alembic("upgrade", "head").returncode == 0

    with _engine().connect() as conn:
        conn.execute(sa.text("ALTER TABLE hypervisor DROP COLUMN IF EXISTS zabbix_server"))
        conn.execute(sa.text("UPDATE alembic_version SET version_num = '0029'"))
        conn.commit()

    res = _alembic("upgrade", "head")
    assert res.returncode == 0, f"la 0030 echoue en ALTER :\n{res.stderr}"

    insp = sa.inspect(_engine())
    assert "zabbix_server" in {c["name"] for c in insp.get_columns("hypervisor")}


def test_la_reservation_didentifiant_de_vm_est_bien_unique_et_partielle():
    """L'index doit refuser deux VM au même numéro, mais tolérer N machines physiques.

    Sans le `WHERE proxmox_vm_id > 0`, la deuxième machine physique — toutes
    portent 0 — serait rejetée, et OSIRIS ne saurait plus déployer un poste.

    On insère via les modèles et non en SQL brut : le schéma porte une trentaine de
    colonnes NOT NULL, qu'un INSERT écrit à la main ne suivrait pas longtemps.
    """
    from sqlmodel import Session as SqlmodelSession

    from models import Hypervisor, Machine

    _wipe()
    assert _alembic("upgrade", "head").returncode == 0

    moteur = _engine()
    with SqlmodelSession(moteur) as session:
        hv = Hypervisor(name="pve", type="proxmox", url="https://pve")
        session.add(hv)
        session.commit()
        session.refresh(hv)
        hv_id = hv.id      # capture DANS la session : `commit` expire l'instance

        # Trois machines physiques : toutes a 0, aucune ne doit gener les autres.
        for i in range(3):
            session.add(Machine(mac=f"aabbccdd00{i:02d}", hostname=f"PC-{i}",
                                client="Acme", os="ubuntu"))
        session.commit()

        session.add(Machine(mac="aabbccddee01", hostname="SRV-1", client="Acme",
                            os="ubuntu", hypervisor_id=hv_id, proxmox_vm_id=150))
        session.commit()

    with SqlmodelSession(moteur) as session:
        session.add(Machine(mac="aabbccddee02", hostname="SRV-2", client="Acme",
                            os="ubuntu", hypervisor_id=hv_id, proxmox_vm_id=150))
        with pytest.raises(sa.exc.IntegrityError):
            session.commit()
