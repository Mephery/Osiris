# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Add vpn_username/vpn_password/requires_totp to vpn_tunnel

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE vpn_tunnel ADD COLUMN IF NOT EXISTS vpn_username VARCHAR NOT NULL DEFAULT ''"))
    bind.execute(sa.text("ALTER TABLE vpn_tunnel ADD COLUMN IF NOT EXISTS vpn_password VARCHAR NOT NULL DEFAULT ''"))
    bind.execute(sa.text("ALTER TABLE vpn_tunnel ADD COLUMN IF NOT EXISTS requires_totp BOOLEAN NOT NULL DEFAULT false"))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE vpn_tunnel DROP COLUMN IF EXISTS requires_totp"))
    bind.execute(sa.text("ALTER TABLE vpn_tunnel DROP COLUMN IF EXISTS vpn_password"))
    bind.execute(sa.text("ALTER TABLE vpn_tunnel DROP COLUMN IF EXISTS vpn_username"))
