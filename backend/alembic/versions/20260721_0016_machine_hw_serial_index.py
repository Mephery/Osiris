# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Index sur machine.hw_serial (identification des machines par numéro de série)

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_machine_hw_serial ON machine (hw_serial)"
    ))


def downgrade() -> None:
    pass
