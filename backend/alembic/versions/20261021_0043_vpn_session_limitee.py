# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""vpn_tunnel.expires_at / closed_at / close_reason : sessions VPN a duree limitee

Un tunnel restait connecte des mois avec le compte nominatif d'un operateur sur le
pare-feu du client. Il s'ouvre desormais pour une duree choisie et se referme seul.

Revision ID: 0043
Revises: 0042
Create Date: 2026-10-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0043"
down_revision: Union[str, None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("ALTER TABLE vpn_tunnel ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ NULL"))
    bind.execute(sa.text("ALTER TABLE vpn_tunnel ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ NULL"))
    bind.execute(sa.text(
        "ALTER TABLE vpn_tunnel ADD COLUMN IF NOT EXISTS close_reason VARCHAR NOT NULL DEFAULT ''"))


def downgrade() -> None:
    bind = op.get_bind()
    for col in ("close_reason", "closed_at", "expires_at"):
        bind.execute(sa.text(f"ALTER TABLE vpn_tunnel DROP COLUMN IF EXISTS {col}"))
