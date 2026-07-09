# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""Hypervisor model for Proxmox integration

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS hypervisor (
            id SERIAL PRIMARY KEY,
            organization_id INTEGER REFERENCES organization(id) ON DELETE SET NULL,
            name VARCHAR NOT NULL,
            type VARCHAR NOT NULL DEFAULT 'proxmox',
            url VARCHAR NOT NULL,
            token_id VARCHAR NOT NULL DEFAULT '',
            token_secret VARCHAR NOT NULL DEFAULT '',
            tls_verify BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))


def downgrade() -> None:
    pass
