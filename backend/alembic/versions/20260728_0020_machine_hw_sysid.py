# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Colonne machine.hw_sysid (identifiant matériel constructeur, MTM chez Lenovo)

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS hw_sysid VARCHAR NOT NULL DEFAULT ''"
    ))
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_machine_hw_sysid ON machine (hw_sysid)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_machine_hw_sysid"))
    bind.execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS hw_sysid"))
