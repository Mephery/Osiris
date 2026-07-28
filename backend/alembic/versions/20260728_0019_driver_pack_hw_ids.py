# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Colonne driver_pack.hw_ids (identifiants matériel du catalogue constructeur)

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "ALTER TABLE driver_pack ADD COLUMN IF NOT EXISTS hw_ids VARCHAR NOT NULL DEFAULT ''"
    ))
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_driver_pack_hw_ids ON driver_pack (hw_ids)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_driver_pack_hw_ids"))
    bind.execute(sa.text("ALTER TABLE driver_pack DROP COLUMN IF EXISTS hw_ids"))
