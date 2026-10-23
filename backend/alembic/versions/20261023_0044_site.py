# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""site : les sites distants et l'etat de la copie de nuit de leur cache

Revision ID: 0044
Revises: 0043
Create Date: 2026-10-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0044"
down_revision: Union[str, None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().execute(sa.text("""
        CREATE TABLE IF NOT EXISTS site (
            id SERIAL PRIMARY KEY,
            nom VARCHAR NOT NULL UNIQUE,
            jeton_empreinte VARCHAR NOT NULL DEFAULT '',
            cree_le TIMESTAMPTZ NOT NULL DEFAULT now(),
            rapport_le TIMESTAMPTZ NULL,
            copie_reussie_le TIMESTAMPTZ NULL,
            erreur VARCHAR NOT NULL DEFAULT '',
            duree_s INTEGER NOT NULL DEFAULT 0,
            octets_recus BIGINT NOT NULL DEFAULT 0,
            images VARCHAR NOT NULL DEFAULT '[]'
        )
    """))


def downgrade() -> None:
    op.get_bind().execute(sa.text("DROP TABLE IF EXISTS site"))
