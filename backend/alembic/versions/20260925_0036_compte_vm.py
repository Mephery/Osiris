# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""compte_vm : le compte d'une personne précise sur une VM

Nom, clé SSH et sudo, enregistrés sur la fiche pour que le premier démarrage —
et un redéploiement — les relisent. Vide = aucun compte en plus de celui du profil.

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS compte TEXT NOT NULL DEFAULT ''"
    ))


def downgrade() -> None:
    op.get_bind().execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS compte"))
