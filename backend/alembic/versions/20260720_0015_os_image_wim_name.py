# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""wim_name on os_image (coexistence de plusieurs WIM Windows sur le partage)

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "ALTER TABLE os_image ADD COLUMN IF NOT EXISTS wim_name VARCHAR NOT NULL DEFAULT ''"
    ))


def downgrade() -> None:
    pass
