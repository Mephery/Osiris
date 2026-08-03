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
    # IF NOT EXISTS obligatoire : sur une base vierge, 0001 fait un
    # SQLModel.metadata.create_all() qui cree deja *toutes* les tables declarees
    # dans models.py aujourd'hui, vpn_tunnel comprise. Un op.create_table() nu
    # echouait donc en "la relation vpn_tunnel existe deja" et cassait toute
    # installation neuve. Meme convention que 0003 (hypervisor).
    bind = op.get_bind()
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS vpn_tunnel (
            id SERIAL PRIMARY KEY,
            organization_id INTEGER NOT NULL UNIQUE REFERENCES organization(id),
            name VARCHAR NOT NULL,
            slug VARCHAR NOT NULL UNIQUE,
            ovpn_config VARCHAR NOT NULL DEFAULT '',
            remote_dns VARCHAR NOT NULL DEFAULT '',
            route_cidr VARCHAR NOT NULL DEFAULT '',
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            status VARCHAR NOT NULL DEFAULT 'unknown',
            last_applied_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    bind.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_vpn_tunnel_organization_id "
        "ON vpn_tunnel (organization_id)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_vpn_tunnel_organization_id"))
    bind.execute(sa.text("DROP TABLE IF EXISTS vpn_tunnel"))
