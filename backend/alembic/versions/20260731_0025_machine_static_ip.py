# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Adressage IP fixe des machines (VLAN serveurs sans DHCP)

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = ["ip_cidr", "gateway", "dns_servers"]


def upgrade() -> None:
    bind = op.get_bind()
    # Vide = DHCP : le comportement des machines existantes ne change pas.
    for name in _COLUMNS:
        bind.execute(sa.text(
            f"ALTER TABLE machine ADD COLUMN IF NOT EXISTS {name} VARCHAR NOT NULL DEFAULT ''"
        ))


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(_COLUMNS):
        bind.execute(sa.text(f"ALTER TABLE machine DROP COLUMN IF EXISTS {name}"))
