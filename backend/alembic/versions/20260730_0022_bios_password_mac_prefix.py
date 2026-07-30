# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Mot de passe administrateur BIOS et prefixe MAC impose, par organisation

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # Chiffre Fernet, jamais en clair en base ni renvoye par l'API.
    bind.execute(sa.text(
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS bios_password VARCHAR NOT NULL DEFAULT ''"
    ))
    bind.execute(sa.text(
        "ALTER TABLE organization ADD COLUMN IF NOT EXISTS mac_prefix VARCHAR NOT NULL DEFAULT ''"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE organization DROP COLUMN IF EXISTS mac_prefix"))
    bind.execute(sa.text("ALTER TABLE organization DROP COLUMN IF EXISTS bios_password"))
