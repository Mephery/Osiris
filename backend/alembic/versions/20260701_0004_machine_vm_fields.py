# SPDX-License-Identifier: LicenseRef-OSIRIS-Fair-Source
# Copyright (c) 2026 Coline Derycke. See LICENSE.
"""VM fields on Machine (hypervisor_id, proxmox_vm_id, proxmox_node)

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    stmts = [
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS hypervisor_id INTEGER REFERENCES hypervisor(id) ON DELETE SET NULL",
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS proxmox_vm_id INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE machine ADD COLUMN IF NOT EXISTS proxmox_node VARCHAR NOT NULL DEFAULT ''",
    ]
    for stmt in stmts:
        bind.execute(sa.text(stmt))


def downgrade() -> None:
    pass
