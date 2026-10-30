# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""capture_job : les captures en cours survivent au redemarrage de l'API

Gardees en memoire seule, elles disparaissaient avec le processus : une VM de
reference restee sur son CD WinPE recevait alors le script de DEPLOIEMENT, qui
efface le disque.

Revision ID: 0048
Revises: 0047
Create Date: 2026-10-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0048"
down_revision: Union[str, None] = "0047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().execute(sa.text("""
        CREATE TABLE IF NOT EXISTS capture_job (
            mac VARCHAR PRIMARY KEY,
            wim_name VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            registered_at VARCHAR NOT NULL,
            finished_at VARCHAR NOT NULL DEFAULT '',
            error VARCHAR NOT NULL DEFAULT '',
            statut_avant VARCHAR NOT NULL DEFAULT ''
        )"""))


def downgrade() -> None:
    op.get_bind().execute(sa.text("DROP TABLE IF EXISTS capture_job"))
