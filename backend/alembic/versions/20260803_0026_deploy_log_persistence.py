# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Persistance du journal de deploiement (table deploy_log_line + compteur sur machine)

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS partout : sur une base vierge, la 0001 a deja cree ces objets via
    # SQLModel.metadata.create_all(). Cf. la section « Migrations » du README.
    bind = op.get_bind()
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS deploy_log_line (
            id SERIAL PRIMARY KEY,
            mac VARCHAR NOT NULL,
            run INTEGER NOT NULL DEFAULT 1,
            timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
            line VARCHAR NOT NULL
        )
    """))
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_deploy_log_line_mac ON deploy_log_line (mac)"
    ))
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_deploy_log_line_run ON deploy_log_line (run)"
    ))
    # Le journal se lit toujours pour un couple (machine, deploiement) : c'est cet
    # index-la qui porte l'affichage live et le comptage anti-boucle, pas les deux
    # index simples ci-dessus (crees par le modele).
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_deploy_log_line_mac_run "
        "ON deploy_log_line (mac, run, id)"
    ))
    bind.execute(sa.text(
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS deploy_log_run "
        "INTEGER NOT NULL DEFAULT 1"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS deploy_log_run"))
    bind.execute(sa.text("DROP TABLE IF EXISTS deploy_log_line"))
