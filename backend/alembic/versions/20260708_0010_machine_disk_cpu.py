# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Add hw_disk_gb/hw_cpu to machine

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE machine ADD COLUMN IF NOT EXISTS hw_disk_gb INTEGER NOT NULL DEFAULT 0"))
    bind.execute(sa.text("ALTER TABLE machine ADD COLUMN IF NOT EXISTS hw_cpu VARCHAR NOT NULL DEFAULT ''"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS hw_cpu"))
    bind.execute(sa.text("ALTER TABLE machine DROP COLUMN IF EXISTS hw_disk_gb"))
