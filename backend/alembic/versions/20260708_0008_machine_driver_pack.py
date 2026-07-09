# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Add driver_pack_id to machine for targeted driver injection

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE machine ADD COLUMN IF NOT EXISTS driver_pack_id INTEGER REFERENCES driver_pack(id)"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS driver_pack_id"))
