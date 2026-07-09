# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Add vpn_tunnel table for per-organization site-to-site VPN routing

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vpn_tunnel",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organization.id"), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False, unique=True),
        sa.Column("ovpn_config", sa.String(), nullable=False, server_default=""),
        sa.Column("remote_dns", sa.String(), nullable=False, server_default=""),
        sa.Column("route_cidr", sa.String(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("last_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_vpn_tunnel_organization_id", "vpn_tunnel", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_vpn_tunnel_organization_id", table_name="vpn_tunnel")
    op.drop_table("vpn_tunnel")
