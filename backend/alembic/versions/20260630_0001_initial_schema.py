"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-30
"""
from typing import Sequence, Union

import sqlmodel
from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- Installation fraiche : cree toutes les tables avec tous leurs champs.
    # -- Base existante : CREATE TABLE IF NOT EXISTS est un no-op, les ALTER TABLE
    #    ajoutent les colonnes manquantes ajoutees incrementalement avant Alembic.
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import models  # noqa - enregistre les modeles dans SQLModel.metadata
    from sqlmodel import SQLModel

    bind = op.get_bind()
    SQLModel.metadata.create_all(bind=bind, checkfirst=True)

    # Colonnes ajoutees incrementalement avant l'introduction d'Alembic.
    # Toutes utilisent IF NOT EXISTS : sans effet sur une base fraiche ou deja a jour.
    stmts = [
        "ALTER TABLE profile ADD COLUMN IF NOT EXISTS app_ids VARCHAR NOT NULL DEFAULT ''",
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS webhook_url VARCHAR NOT NULL DEFAULT ''",
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS hw_serial VARCHAR NOT NULL DEFAULT ''",
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS hw_model VARCHAR NOT NULL DEFAULT ''",
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS hw_ram_gb INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS bitlocker_key VARCHAR NOT NULL DEFAULT ''",
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS notes VARCHAR NOT NULL DEFAULT ''",
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS bitlocker_pin VARCHAR NOT NULL DEFAULT ''",
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS laps_password VARCHAR NOT NULL DEFAULT ''",
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS user_name VARCHAR NOT NULL DEFAULT ''",
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS user_email VARCHAR NOT NULL DEFAULT ''",
        "ALTER TABLE profile ADD COLUMN IF NOT EXISTS enable_bitlocker BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE profile ADD COLUMN IF NOT EXISTS bitlocker_pin BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE profile ADD COLUMN IF NOT EXISTS network_drives VARCHAR NOT NULL DEFAULT ''",
        "ALTER TABLE profile ADD COLUMN IF NOT EXISTS printers VARCHAR NOT NULL DEFAULT ''",
        "ALTER TABLE profile ADD COLUMN IF NOT EXISTS post_script TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE profile ADD COLUMN IF NOT EXISTS domain_config_id INTEGER REFERENCES domain_config(id) ON DELETE SET NULL",
        'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS totp_secret VARCHAR NOT NULL DEFAULT \'\'',
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS smoke_status VARCHAR NOT NULL DEFAULT ''",
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS smoke_results VARCHAR NOT NULL DEFAULT ''",
        "ALTER TABLE profile ADD COLUMN IF NOT EXISTS laps_rotation_days INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS laps_rotated_at TIMESTAMP",
    ]
    for stmt in stmts:
        bind.execute(sa.text(stmt))


def downgrade() -> None:
    # Downgrade non implemente pour la migration initiale.
    pass
