# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""site.inachevee : copie coupee par la fin de sa fenetre de nuit

Une premiere copie dure plusieurs nuits : l'afficher « en echec » faisait
chercher une panne la ou la copie reprend simplement la nuit suivante.

Revision ID: 0045
Revises: 0044
Create Date: 2026-10-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0045"
down_revision: Union[str, None] = "0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE site ADD COLUMN IF NOT EXISTS inachevee BOOLEAN NOT NULL DEFAULT FALSE"))


def downgrade() -> None:
    op.get_bind().execute(sa.text("ALTER TABLE site DROP COLUMN IF EXISTS inachevee"))
