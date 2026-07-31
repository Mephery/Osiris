# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""URL de rappel d'OSIRIS propre a chaque hyperviseur

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # Vide = on garde OSIRIS_BASE_URL : les hyperviseurs existants ne changent pas
    # de comportement.
    bind.execute(sa.text(
        "ALTER TABLE hypervisor ADD COLUMN IF NOT EXISTS callback_url VARCHAR NOT NULL DEFAULT ''"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE hypervisor DROP COLUMN IF EXISTS callback_url"))
