# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Add snippets_storage to Hypervisor for cloud-init support

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "ALTER TABLE hypervisor ADD COLUMN IF NOT EXISTS snippets_storage VARCHAR NOT NULL DEFAULT ''"
    ))


def downgrade() -> None:
    pass
