# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Add custom installer fields to application (install_type/installer_file/install_args)

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE application ADD COLUMN IF NOT EXISTS install_type VARCHAR NOT NULL DEFAULT 'winget'"))
    bind.execute(sa.text("ALTER TABLE application ADD COLUMN IF NOT EXISTS installer_file VARCHAR NOT NULL DEFAULT ''"))
    bind.execute(sa.text("ALTER TABLE application ADD COLUMN IF NOT EXISTS install_args VARCHAR NOT NULL DEFAULT ''"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE application DROP COLUMN IF EXISTS install_args"))
    bind.execute(sa.text("ALTER TABLE application DROP COLUMN IF EXISTS installer_file"))
    bind.execute(sa.text("ALTER TABLE application DROP COLUMN IF EXISTS install_type"))
