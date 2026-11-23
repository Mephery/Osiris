# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""machine.winpe_envoye_le : WinPE envoye, pas encore de signe de vie

Un PC dont le firmware refuse de demarrer WinPE repart sur le Windows de son
disque : aucun appel ne revient, et la fiche restait « deploying » sans fin.
Cet horodatage, pose par /boot et efface au rappel de WinPE, permet de
detecter ce silence et de le dire.

Revision ID: 0049
Revises: 0048
Create Date: 2026-11-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0049"
down_revision: Union[str, None] = "0048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS winpe_envoye_le TIMESTAMP WITHOUT TIME ZONE"))


def downgrade() -> None:
    op.get_bind().execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS winpe_envoye_le"))
