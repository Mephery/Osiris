# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Add installer_config_file to application (companion file, e.g. Office ODT config XML)

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE application ADD COLUMN IF NOT EXISTS installer_config_file VARCHAR NOT NULL DEFAULT ''"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE application DROP COLUMN IF EXISTS installer_config_file"))
